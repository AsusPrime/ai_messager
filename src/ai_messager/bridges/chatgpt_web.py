from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
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

            # ChatGPT virtualizes the chat list — old turns mount/unmount
            # as we interact, so anchoring to a specific assistant turn by
            # id or index is unreliable. Instead we operate on page-level
            # invariants: snapshot the current "last assistant turn text"
            # before sending and watch for it to (a) change, then (b)
            # stabilize, in concert with the stop-button visibility cycle.
            text_before_send = await self._last_assistant_text(page)

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

            try:
                text = await self._wait_for_response(
                    page, text_before_send=text_before_send
                )
            except PlaywrightTimeoutError as exc:
                await self._capture_debug_artifact(page, "generation_end")
                raise LLMResponseTimeout(
                    self.provider_name,
                    self._settings.response_timeout_s,
                    stage="generation_end",
                ) from exc

            return text.strip()

    async def _wait_for_response(self, page: Page, *, text_before_send: str) -> str:
        """Wait until the assistant has produced a stable new response.

        Operates on page-level state to avoid anchoring to a specific
        assistant-turn DOM node — ChatGPT virtualizes the chat list and
        any specific turn can mount/unmount mid-stream.

        Two debounced signals race; the first to fire returns the text
        of the last assistant turn at that moment:
          - text_changed_then_stable: the last assistant turn's text
            differs from `text_before_send` (i.e. a new response began)
            AND has been unchanged for stream_stable_ms.
          - stop_button_present_then_gone: the stop-button has been
            seen present (streaming started) and then continuously
            absent for stream_stable_ms.
        Bounded by response_timeout_s. On timeout raises PlaywrightTimeoutError.
        """
        timeout_s = self._settings.response_timeout_s
        stable_ms = self._settings.stream_stable_ms
        poll_ms = self._settings.stream_poll_ms
        stop = ChatGPTSelectors.stop_button(page)

        deadline = time.monotonic() + timeout_s
        text_changed = False
        last_text: str = text_before_send
        text_stable_since: float | None = None
        stop_seen_present = False
        stop_gone_since: float | None = None

        while time.monotonic() < deadline:
            current = await self._last_assistant_text(page)
            try:
                stop_present = await stop.count() > 0
            except PlaywrightError:
                stop_present = True  # treat as "still streaming"

            now = time.monotonic()

            # --- text-stability signal -----------------------------------
            if current != text_before_send:
                text_changed = True
            if text_changed:
                if current != last_text:
                    last_text = current
                    text_stable_since = now
                elif (
                    current
                    and text_stable_since is not None
                    and (now - text_stable_since) * 1000 >= stable_ms
                ):
                    log.bind(signal="text_stable", text_len=len(current)).debug(
                        "response_done"
                    )
                    return current

            # --- stop-button-gone signal ---------------------------------
            if stop_present:
                stop_seen_present = True
                stop_gone_since = None
            elif stop_seen_present:
                if stop_gone_since is None:
                    stop_gone_since = now
                elif (now - stop_gone_since) * 1000 >= stable_ms:
                    final = await self._last_assistant_text(page)
                    log.bind(signal="stop_gone", text_len=len(final)).debug(
                        "response_done"
                    )
                    return final

            await asyncio.sleep(poll_ms / 1000)

        raise PlaywrightTimeoutError(
            "no debounced end-of-stream signal fired within timeout"
        )

    async def _last_assistant_text(self, page: Page) -> str:
        """Return innerText of the last [data-message-author-role=assistant]
        element in document order, or "" if none/error.

        Page-level rather than locator-anchored to avoid breaking when
        ChatGPT lazy-mounts/unmounts older turns during interaction.
        """
        try:
            return await page.evaluate(
                "() => {"
                "  const els = document.querySelectorAll("
                "    '[data-message-author-role=\"assistant\"]'"
                "  );"
                "  if (!els.length) return '';"
                "  return (els[els.length - 1].innerText || '').trim();"
                "}"
            )
        except PlaywrightError:
            return ""

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
