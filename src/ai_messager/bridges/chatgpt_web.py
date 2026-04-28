from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ai_messager.bridges.base import LLMBridge
from ai_messager.core.exceptions import (
    ChatNotFound,
    CloudflareChallenge,
    LLMResponseTimeout,
    NotLoggedIn,
)
from ai_messager.selectors.chatgpt import ChatGPTSelectors
from ai_messager.utils.logger import get_logger

log = get_logger(__name__)


class ChatGPTBridge(LLMBridge):
    provider_name: ClassVar[str] = "chatgpt_web"
    home_url: ClassVar[str] = "https://chatgpt.com/"
    default_chat_path: ClassVar[str] = "/"

    # Cookies are diagnosed across chatgpt.com plus every OAuth hop the
    # NextAuth → Google sign-in flow goes through. Cookie VALUES are never
    # logged — only names, domains and value lengths.
    diagnostic_cookie_domains: ClassVar[tuple[str, ...]] = (
        "https://chatgpt.com/",
        "https://auth.openai.com/",
        "https://openai.com/",
        "https://accounts.google.com/",
    )

    # OpenAI uses NextAuth. After a successful sign-in the callback sets a
    # secure, httpOnly session cookie on chatgpt.com. Its presence is a clean,
    # DOM-independent signal that the user is authenticated.
    #
    # Large JWTs exceed the 4KB per-cookie browser limit, so NextAuth splits
    # them across chunked cookies named "<base>.0", "<base>.1", etc. We must
    # accept either shape.
    _SESSION_COOKIE_BASE: ClassVar[str] = "__Secure-next-auth.session-token"

    # Cloudflare Turnstile injects async ~200-1000ms after navigation. Short
    # wait avoids both false negatives (widget not yet mounted) and long hangs.
    _CLOUDFLARE_CHECK_TIMEOUT_MS: ClassVar[int] = 2000
    # Send button visibility wait before falling back to Enter keypress.
    _SEND_BUTTON_WAIT_MS: ClassVar[int] = 2000
    # ProseMirror needs real per-char input events; this is the inter-key delay.
    _COMPOSER_TYPING_DELAY_MS: ClassVar[int] = 10
    # After typing finishes, give React time to enable the Send button.
    _REACT_SETTLE_MS: ClassVar[int] = 150

    async def is_logged_in(self, page: Page) -> bool:
        """Check login state by inspecting cookies for the session token.

        Cookie-based check avoids DOM timing issues (rendered-yet? auth redirect
        in progress? JS hydration?) and never requires navigation.
        """
        cookies = await page.context.cookies("https://chatgpt.com/")
        base = self._SESSION_COOKIE_BASE
        chunk_prefix = f"{base}."
        for cookie in cookies:
            name = cookie.get("name") or ""
            if name == base or name.startswith(chunk_prefix):
                value = cookie.get("value") or ""
                # Guard against empty/placeholder cookies during redirects.
                if len(value) > 20:
                    return True
        return False

    async def ask(self, message: str, chat_url: str | None) -> str:
        """Send a message and return the assistant's reply.

        If chat_url is None, navigate to home_url (fresh chat). Otherwise,
        navigate to the pinned conversation URL. The single shared Page is
        reused across calls so Cloudflare / CDN state stays warm.
        """
        target = chat_url or self.home_url
        ui_timeout = self._settings.ui_ready_timeout_ms

        async with self._session.page() as page:
            await self._ensure_on(page, target, chat_url=chat_url)

            try:
                await ChatGPTSelectors.cloudflare_prompt(page).wait_for(
                    state="visible", timeout=self._CLOUDFLARE_CHECK_TIMEOUT_MS
                )
            except PlaywrightTimeoutError:
                pass  # no challenge
            else:
                await self._capture_debug_artifact(page, "cloudflare")
                raise CloudflareChallenge(self.provider_name)

            if not await self.is_logged_in(page):
                raise NotLoggedIn(self.provider_name)

            composer = ChatGPTSelectors.composer(page)
            try:
                await composer.wait_for(state="visible", timeout=ui_timeout)
            except PlaywrightTimeoutError as exc:
                await self._capture_debug_artifact(page, "composer_visible")
                raise LLMResponseTimeout(
                    self.provider_name,
                    ui_timeout // 1000,
                    stage="composer_visible",
                ) from exc

            # Snapshot the current turn count so we can tell when a new one
            # arrives. Relying on "stop-button disappears" is unreliable: the
            # button can flash between streaming frames and the hidden-state
            # wait can return early, giving us partial text like "Result l".
            assistant_turns = ChatGPTSelectors.assistant_turns(page)
            turns_before = await assistant_turns.count()

            # ChatGPT's composer is a ProseMirror contenteditable, not a plain
            # textarea. Locator.fill() bypasses ProseMirror's input handlers,
            # so React state never updates and the Send button never enables.
            # click() + press_sequentially() dispatches real per-char input
            # events, which ProseMirror picks up correctly.
            await composer.click()
            await composer.press_sequentially(
                message, delay=self._COMPOSER_TYPING_DELAY_MS
            )
            await page.wait_for_timeout(self._REACT_SETTLE_MS)

            # Prefer clicking the Send button — it bypasses any Enter-sends
            # vs. Shift+Enter user setting. Fall back to pressing Enter if
            # the button testid isn't found (older UI variants).
            send = ChatGPTSelectors.send_button(page)
            try:
                await send.wait_for(state="visible", timeout=self._SEND_BUTTON_WAIT_MS)
                await send.click()
            except PlaywrightTimeoutError:
                await composer.press("Enter")

            # Wait for a brand-new assistant turn to be appended.
            try:
                await page.wait_for_function(
                    "count => document.querySelectorAll("
                    "'[data-message-author-role=\"assistant\"]'"
                    ").length > count",
                    arg=turns_before,
                    timeout=ui_timeout,
                )
            except PlaywrightTimeoutError as exc:
                await self._capture_debug_artifact(page, "generation_start")
                raise LLMResponseTimeout(
                    self.provider_name,
                    ui_timeout // 1000,
                    stage="generation_start",
                ) from exc

            new_turn = assistant_turns.nth(turns_before)

            try:
                text = await self._wait_for_stream_end(new_turn)
            except PlaywrightTimeoutError as exc:
                await self._capture_debug_artifact(page, "generation_end")
                raise LLMResponseTimeout(
                    self.provider_name,
                    self._settings.response_timeout_s,
                    stage="generation_end",
                ) from exc

            return text.strip()

    async def _wait_for_stream_end(self, turn: Locator) -> str:
        """Wait until generation finishes; return final turn text.

        Two signals race; the first to succeed wins:
          - Primary: a per-turn action button (Copy / Good response / etc.)
            mounts inside the turn — ChatGPT only renders those AFTER
            streaming ends. Robust against mid-stream pauses (reasoning
            models, multi-phase replies) that broke the old text-stability
            heuristic.
          - Fallback: turn text stays unchanged for stream_stable_ms.
            Survives a testid rename until selectors are patched.
        Both share response_timeout_s as the deadline. Raises
        PlaywrightTimeoutError if neither fires in time.
        """
        primary = asyncio.create_task(self._wait_for_action_button(turn))
        fallback = asyncio.create_task(self._wait_for_text_stable(turn))
        pending: set[asyncio.Task[None]] = {primary, fallback}
        last_exc: BaseException | None = None

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    exc = task.exception()
                    if exc is None:
                        return (await turn.inner_text()).strip()
                    last_exc = exc
        finally:
            for task in pending:
                task.cancel()

        assert last_exc is not None
        raise last_exc

    async def _wait_for_action_button(self, turn: Locator) -> None:
        # state="attached" — not "visible". The buttons mount in the DOM
        # the moment streaming ends, but their parent has `opacity-0` +
        # `group-hover:opacity-100`, so they are never `visible` without a
        # mouse hover (and never in headless). DOM-presence is the real
        # signal we want.
        timeout_ms = self._settings.response_timeout_s * 1000
        button = ChatGPTSelectors.turn_action_button(turn)
        await button.wait_for(state="attached", timeout=timeout_ms)

    async def _wait_for_text_stable(self, turn: Locator) -> None:
        timeout_s = self._settings.response_timeout_s
        stable_ms = self._settings.stream_stable_ms
        poll_ms = self._settings.stream_poll_ms

        deadline = time.monotonic() + timeout_s
        previous: str | None = None
        stable_since: float | None = None

        while time.monotonic() < deadline:
            try:
                current = (await turn.inner_text()).strip()
            except PlaywrightError:
                # Turn may detach briefly during React re-renders.
                current = ""

            now = time.monotonic()
            if current != previous:
                previous = current
                stable_since = now
            elif (
                current
                and stable_since is not None
                and (now - stable_since) * 1000 >= stable_ms
            ):
                return

            await asyncio.sleep(poll_ms / 1000)

        raise PlaywrightTimeoutError("text never stabilized within timeout")

    async def _ensure_on(
        self, page: Page, target: str, *, chat_url: str | None
    ) -> None:
        """Navigate to target if we're not already there. Idempotent.

        Skips navigation when the current URL already matches (ignoring a
        trailing slash). If the target is a pinned chat URL and navigation
        fails, raise ChatNotFound so callers can surface a clean error.
        """
        if page.url.rstrip("/") == target.rstrip("/"):
            return
        try:
            await page.goto(target, wait_until="domcontentloaded")
        except PlaywrightError as exc:
            if chat_url is not None:
                raise ChatNotFound(chat_url) from exc
            raise

    async def _capture_debug_artifact(self, page: Page, stage: str) -> Path | None:
        """Dump a full-page screenshot + URL/HTML snapshot when ask() times out.

        Returns the screenshot path, or None if capture itself failed. Never raises.
        """
        artifacts_dir = self._settings.screenshots_dir
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%dT%H%M%S")
            shot = artifacts_dir / f"{ts}_{stage}.png"
            html = artifacts_dir / f"{ts}_{stage}.html"
            await page.screenshot(path=str(shot), full_page=True)
            try:
                html.write_text(await page.content(), encoding="utf-8")
            except Exception as exc:
                log.bind(error=str(exc)).warning("Debug HTML dump failed")
            log.bind(stage=stage, url=page.url, screenshot=str(shot)).info(
                "Debug artifact captured"
            )
            return shot
        except Exception as exc:
            log.bind(stage=stage, error=str(exc)).warning("Debug artifact failed")
            return None
