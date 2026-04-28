from __future__ import annotations

import asyncio
import sys
import time
from typing import ClassVar

import typer
from playwright.async_api import Page
from rich.console import Console
from rich.table import Table

from ai_messager.bridges.base import LLMBridge
from ai_messager.bridges.registry import BridgeRegistry, build_default_registry
from ai_messager.browser.session import BrowserSession
from ai_messager.core.config import AppConfig, Settings, load_app_config
from ai_messager.core.exceptions import ProviderNotRegistered
from ai_messager.utils.logger import get_logger, setup_logger

app = typer.Typer(
    name="ai-messager",
    help="MCP bridge between Claude and web-based LLM chats.",
    no_args_is_help=True,
)

console = Console()
log = get_logger(__name__)

# CLI is the entrypoint — it owns the registry. Built once at import so
# typer can render the dynamic provider list in --help.
_registry = build_default_registry()


# --------------------------------------------------------------------------
# LOGIN
# --------------------------------------------------------------------------


class LoginFlow:
    """Open a visible browser, poll for sign-in, log diagnostic cookie state."""

    # Login detection requires the success signal twice in a row to avoid
    # false positives during quick redirects that briefly land on chatgpt.com.
    _SUCCESS_STREAK_REQUIRED: ClassVar[int] = 2

    def __init__(
        self,
        *,
        provider: str,
        bridge_cls: type[LLMBridge],
        settings: Settings,
        max_wait_s: int,
    ) -> None:
        self._provider = provider
        self._bridge_cls = bridge_cls
        self._settings = settings
        self._max_wait_s = max_wait_s
        self._cookie_domains = bridge_cls.diagnostic_cookie_domains

    async def run(self) -> int:
        profile_dir = self._settings.profile_dir_for(self._provider)
        session = BrowserSession(
            provider=self._provider,
            user_data_dir=profile_dir,
            headless=False,
            channel=self._settings.browser_channel,
        )
        await session.start()
        bridge = self._bridge_cls(session, self._settings)

        try:
            async with session.raw_page() as page:
                # Navigate ONCE. After this, the user may be redirected
                # through auth.openai.com / accounts.google.com / etc. We
                # must never force them back to chatgpt.com during the flow
                # — is_logged_in() is a pure DOM read.
                await page.goto(bridge.home_url, wait_until="domcontentloaded")

                initial = await self._snapshot_cookies(page, when="after_initial_nav")
                console.print(
                    f"[dim]cookies @ initial nav ({page.url}):[/dim] "
                    f"{self._render_cookie_names(initial)}"
                )

                if await bridge.is_logged_in(page):
                    console.print(
                        f"[green]Already signed in[/green] to {self._provider}. "
                        f"Closing window."
                    )
                    await asyncio.sleep(self._settings.login_settle_s)
                    return 0

                console.print(
                    f"[cyan]Opened browser for {self._provider}.[/cyan] "
                    f"Sign in in the window — I'll close it automatically once you're in.\n"
                    f"Profile dir: [dim]{profile_dir}[/dim]\n"
                    f"Timeout: [dim]{self._max_wait_s}s[/dim]\n"
                    f"Browser channel: [dim]{self._settings.browser_channel or 'chromium (bundled)'}[/dim]\n"
                    f"Full cookie snapshots → "
                    f"[dim]{self._settings.logs_dir / 'ai_messager.log'}[/dim]"
                )

                last_snapshot = await self._poll_until_logged_in(page, bridge, initial)
                if last_snapshot is None:
                    return 0
                self._render_timeout_diagnostics(last_snapshot)
                return 1
        finally:
            await session.aclose()

    async def _poll_until_logged_in(
        self,
        page: Page,
        bridge: LLMBridge,
        initial_snapshot: list[dict],
    ) -> list[dict] | None:
        """Poll login status. Returns None on success, last snapshot on timeout."""
        deadline = time.monotonic() + self._max_wait_s
        poll = self._settings.login_poll_interval_s
        consecutive_success = 0
        last_snapshot = initial_snapshot
        tick = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(poll)
            tick += 1
            last_snapshot = await self._snapshot_cookies(page, when=f"poll_{tick}")
            console.print(
                f"[dim]poll {tick} @ {page.url}:[/dim] "
                f"{self._render_cookie_names(last_snapshot)}"
            )
            if await bridge.is_logged_in(page):
                consecutive_success += 1
                if consecutive_success >= self._SUCCESS_STREAK_REQUIRED:
                    profile_dir = self._settings.profile_dir_for(self._provider)
                    console.print(
                        "[green]Login detected.[/green] Letting cookies settle…"
                    )
                    await asyncio.sleep(self._settings.login_settle_s)
                    console.print(
                        f"[green]Done.[/green] Profile saved to [bold]{profile_dir}[/bold]"
                    )
                    return None
            else:
                consecutive_success = 0

        await self._snapshot_cookies(page, when="timeout")
        return last_snapshot

    async def _snapshot_cookies(self, page: Page, *, when: str) -> list[dict]:
        """Dump cookie metadata for diagnosis. Never logs cookie values."""
        seen: set[tuple[str | None, str | None]] = set()
        snapshot: list[dict] = []
        for url in self._cookie_domains:
            try:
                cookies = await page.context.cookies(url)
            except Exception as exc:
                log.bind(domain=url, error=str(exc)).warning("Cookie snapshot failed")
                continue
            for cookie in cookies:
                key = (cookie.get("name"), cookie.get("domain"))
                if key in seen:
                    continue
                seen.add(key)
                snapshot.append(
                    {
                        "name": cookie.get("name"),
                        "domain": cookie.get("domain"),
                        "value_len": len(cookie.get("value") or ""),
                        "http_only": cookie.get("httpOnly"),
                        "secure": cookie.get("secure"),
                    }
                )
        log.bind(
            when=when,
            url=page.url,
            count=len(snapshot),
            cookies=snapshot,
        ).info("Cookie snapshot")
        return snapshot

    @staticmethod
    def _render_cookie_names(snapshot: list[dict]) -> str:
        if not snapshot:
            return "(none)"
        return " ".join(
            f"{c['name']}@{c['domain']}(len={c['value_len']})" for c in snapshot
        )

    def _render_timeout_diagnostics(self, last_snapshot: list[dict]) -> None:
        console.print(
            f"[red]Timed out after {self._max_wait_s}s without detecting login.[/red]"
        )
        console.print("[yellow]Last cookie snapshot:[/yellow]")
        if not last_snapshot:
            console.print("  [dim](no cookies seen on any tracked domain)[/dim]")
        else:
            for c in last_snapshot:
                console.print(
                    f"  • [cyan]{c['name']}[/cyan]@{c['domain']} "
                    f"(len={c['value_len']}, httpOnly={c['http_only']}, secure={c['secure']})"
                )
        console.print(
            "[dim]Send this list — it tells us what auth cookie ChatGPT actually "
            "sets so we can adjust the detector.[/dim]"
        )


@app.command()
def login(
    provider: str = typer.Argument(
        ...,
        help=f"Provider to sign in to. Known: {', '.join(_registry.known())}.",
    ),
    max_wait_s: int = typer.Option(
        None,
        "--max-wait",
        help="Max seconds to wait for login before giving up. Default: from settings.",
    ),
) -> None:
    """Open a visible browser, wait for the user to sign in, close when detected."""
    settings = Settings()
    setup_logger(settings.logs_dir, settings.log_level)

    try:
        bridge_cls = _registry.get(provider)
    except Exception as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=2) from exc

    timeout = max_wait_s if max_wait_s is not None else settings.login_max_wait_s
    flow = LoginFlow(
        provider=provider,
        bridge_cls=bridge_cls,
        settings=settings,
        max_wait_s=timeout,
    )
    exit_code = asyncio.run(flow.run())
    raise typer.Exit(code=exit_code)


# --------------------------------------------------------------------------
# ASK
# --------------------------------------------------------------------------


@app.command()
def ask(
    endpoint: str = typer.Argument(
        ..., help="Endpoint name from config.yaml (without 'ask_' prefix)."
    ),
    message: str = typer.Argument(..., help="Message to send."),
    headless: bool = typer.Option(
        True,
        "--headless/--show",
        help="Run the browser headless (default) or visible for debugging.",
    ),
) -> None:
    """Call a configured endpoint directly — no MCP loop, no Claude in the loop.

    Useful for end-to-end testing the bridge: scrape, selectors, login,
    stream-end detection. Prints the assistant's reply to stdout.
    """
    settings = Settings()
    if not headless:
        settings = settings.model_copy(update={"serve_headless": False})
    setup_logger(settings.logs_dir, settings.log_level)

    try:
        cfg = load_app_config(settings.config_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=2) from exc

    ep = next((e for e in cfg.endpoints if e.name == endpoint), None)
    if ep is None:
        known = ", ".join(e.name for e in cfg.endpoints) or "(none)"
        console.print(f"[red]error[/red] unknown endpoint {endpoint!r}. Known: {known}")
        raise typer.Exit(code=2)

    async def _run() -> str:
        session = BrowserSession(
            provider=ep.provider,
            user_data_dir=settings.profile_dir_for(ep.provider),
            headless=settings.serve_headless,
            channel=settings.browser_channel,
        )
        try:
            bridge_cls = _registry.get(ep.provider)
            bridge = bridge_cls(session, settings)
            return await bridge.ask(message, str(ep.chat_url) if ep.chat_url else None)
        finally:
            await session.aclose()

    try:
        reply = asyncio.run(_run())
    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}[/red]: {exc}")
        raise typer.Exit(code=1) from exc

    console.rule(f"[cyan]ask_{endpoint}[/cyan]  ([dim]{len(reply)} chars[/dim])")
    print(reply)


# --------------------------------------------------------------------------
# SERVE
# --------------------------------------------------------------------------


@app.command()
def serve() -> None:
    """Start the stdio MCP server.

    stdout is reserved for MCP JSON-RPC framing. Nothing else must ever go
    there — logs are forced to stderr + file, and this command deliberately
    avoids console.print on the success path.
    """
    settings = Settings()
    setup_logger(settings.logs_dir, settings.log_level, stdio_server=True)

    try:
        cfg = load_app_config(settings.config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(code=2) from exc

    # Imported here so `ai-messager --help` doesn't pay the import cost.
    from ai_messager.server import MCPServer

    mcp = MCPServer(settings, cfg, _registry)
    asyncio.run(mcp.run())


# --------------------------------------------------------------------------
# STATUS
# --------------------------------------------------------------------------


class StatusProbe:
    """Boots a headless session per provider, reads cookies, closes."""

    _STATE_PALETTE: ClassVar[dict[str, str]] = {
        "logged in": "[green]logged in[/green]",
        "expired": "[yellow]expired[/yellow]",
        "no profile": "[red]no profile[/red]",
        "unknown provider": "[red]unknown[/red]",
        "probe failed": "[red]probe failed[/red]",
        "profile busy": "[yellow]profile busy[/yellow]",
    }

    def __init__(self, settings: Settings, registry: BridgeRegistry) -> None:
        self._settings = settings
        self._registry = registry

    async def probe_all(self, cfg: AppConfig) -> dict[str, str]:
        """Return provider → state string. Fast: <2 s per provider on warm profiles."""
        providers = sorted({ep.provider for ep in cfg.endpoints})
        states: dict[str, str] = {}
        for provider in providers:
            states[provider] = await self._probe_one(provider)
        return states

    async def _probe_one(self, provider: str) -> str:
        profile_dir = self._settings.profile_dir_for(provider)
        if not profile_dir.exists() or not any(profile_dir.iterdir()):
            return "no profile"
        try:
            bridge_cls = self._registry.get(provider)
        except ProviderNotRegistered:
            return "unknown provider"

        session = BrowserSession(
            provider=provider,
            user_data_dir=profile_dir,
            headless=True,
            channel=self._settings.browser_channel,
        )
        try:
            await session.start()
            bridge = bridge_cls(session, self._settings)
            async with session.raw_page() as page:
                ok = await bridge.is_logged_in(page)
            return "logged in" if ok else "expired"
        except Exception as exc:
            state = self._classify_probe_error(exc)
            log.bind(provider=provider, state=state, error=str(exc)).warning(
                "Status probe failed"
            )
            return state
        finally:
            await session.aclose()

    @staticmethod
    def _classify_probe_error(exc: Exception) -> str:
        # Chrome refuses to open a profile that another Chrome process
        # already holds. See system_risks.R-04 — commonly hit when the
        # MCP serve subprocess is running against the same profile.
        msg = str(exc).lower()
        if "processsingleton" in msg or "already in use" in msg:
            return "profile busy"
        return "probe failed"

    @classmethod
    def render_state(cls, state: str) -> str:
        return cls._STATE_PALETTE.get(state, state)


@app.command()
def status() -> None:
    """Show configured endpoints with per-provider login state."""
    settings = Settings()
    setup_logger(settings.logs_dir, settings.log_level)
    try:
        cfg = load_app_config(settings.config_path)
    except FileNotFoundError as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=2) from exc

    probe = StatusProbe(settings, _registry)
    login_states = asyncio.run(probe.probe_all(cfg))

    table = Table(title="ai-messager endpoints")
    table.add_column("Tool name", style="cyan")
    table.add_column("Provider")
    table.add_column("Login", justify="center")
    table.add_column("Chat URL")
    table.add_column("Description", overflow="fold")

    for ep in cfg.endpoints:
        state = login_states.get(ep.provider, "unknown")
        table.add_row(
            f"ask_{ep.name}",
            ep.provider,
            StatusProbe.render_state(state),
            str(ep.chat_url) if ep.chat_url else "[dim](fresh chat)[/dim]",
            ep.description.strip(),
        )
    console.print(table)


# --------------------------------------------------------------------------
# DOCTOR
# --------------------------------------------------------------------------


class DoctorChecks:
    """Sanity checks for installation, writable dirs, valid config."""

    def __init__(self, settings: Settings, registry: BridgeRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._cfg: AppConfig | None = None

    def run(self) -> list[str]:
        problems: list[str] = []
        problems.extend(self._check_playwright())
        problems.extend(self._check_writable_dirs())
        problems.extend(self._check_config())
        problems.extend(self._check_providers())
        return problems

    @staticmethod
    def _check_playwright() -> list[str]:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError as exc:
            return [
                f"playwright not importable: {exc}. Run `uv sync` then "
                f"`uv run playwright install chromium`."
            ]
        return []

    def _check_writable_dirs(self) -> list[str]:
        problems: list[str] = []
        for name, path in (
            ("profiles_dir", self._settings.profiles_dir),
            ("logs_dir", self._settings.logs_dir),
            ("responses_dir", self._settings.responses_dir),
            ("screenshots_dir", self._settings.screenshots_dir),
        ):
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".doctor_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError as exc:
                problems.append(f"{name} ({path}) not writable: {exc}")
        return problems

    def _check_config(self) -> list[str]:
        # Absence is a distinct problem from corruption.
        try:
            self._cfg = load_app_config(self._settings.config_path)
            return []
        except FileNotFoundError:
            return [
                f"config missing at {self._settings.config_path}. Copy "
                f"config.example.yaml there and edit."
            ]
        except Exception as exc:
            return [f"config at {self._settings.config_path} failed to parse: {exc}"]

    def _check_providers(self) -> list[str]:
        if self._cfg is None:
            return []
        problems: list[str] = []
        for ep in self._cfg.endpoints:
            try:
                self._registry.get(ep.provider)
            except ProviderNotRegistered as exc:
                problems.append(
                    f"endpoint {ep.name!r} uses unknown provider "
                    f"{ep.provider!r}: {exc}"
                )
        return problems


@app.command()
def doctor() -> None:
    """Run sanity checks: Playwright install, writable dirs, valid config."""
    settings = Settings()
    checks = DoctorChecks(settings, _registry)
    problems = checks.run()

    if not problems:
        console.print("[green]All checks passed.[/green]")
        console.print(f"  profiles_dir:    [dim]{settings.profiles_dir}[/dim]")
        console.print(f"  logs_dir:        [dim]{settings.logs_dir}[/dim]")
        console.print(f"  responses_dir:   [dim]{settings.responses_dir}[/dim]")
        console.print(f"  screenshots_dir: [dim]{settings.screenshots_dir}[/dim]")
        console.print(f"  config:          [dim]{settings.config_path}[/dim]")
        return

    console.print(f"[red]Found {len(problems)} issue(s):[/red]")
    for problem in problems:
        console.print(f"  • {problem}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
