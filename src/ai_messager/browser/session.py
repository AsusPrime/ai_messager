from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from ai_messager.utils.logger import get_logger

log = get_logger(__name__)


class BrowserSession:
    """Owns one persistent Playwright context tied to a user_data_dir.

    One session = one profile on disk = one logged-in provider. A session
    reuses a single Page across requests to keep Cloudflare/CDN state warm.
    """

    _DEFAULT_VIEWPORT: ClassVar[tuple[int, int]] = (1280, 900)
    _LAUNCH_ARGS: ClassVar[tuple[str, ...]] = (
        "--disable-blink-features=AutomationControlled",
    )
    # Strip "HeadlessChrome" from the UA — Cloudflare and similar bot
    # detectors flag any UA containing that token. We advertise a recent
    # Mac Chrome regardless of whether we're actually headless, so the
    # fingerprint line matches what a normal user presents.
    _USER_AGENT: ClassVar[str] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        provider: str,
        user_data_dir: Path,
        *,
        headless: bool = True,
        channel: str | None = "chrome",
    ) -> None:
        self._provider = provider
        self._user_data_dir = user_data_dir
        self._headless = headless
        self._channel = channel

        self._lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def user_data_dir(self) -> Path:
        return self._user_data_dir

    async def start(self) -> None:
        if self._context is not None:
            return
        self._user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        width, height = self._DEFAULT_VIEWPORT
        launch_kwargs: dict = {
            "user_data_dir": str(self._user_data_dir),
            "headless": self._headless,
            "viewport": {"width": width, "height": height},
            "args": list(self._LAUNCH_ARGS),
            "user_agent": self._USER_AGENT,
        }
        if self._channel:
            launch_kwargs["channel"] = self._channel
        self._context = await self._playwright.chromium.launch_persistent_context(
            **launch_kwargs
        )
        # Reuse the single page Chrome opened, or create one if none exists.
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        log.bind(
            provider=self._provider,
            user_data_dir=str(self._user_data_dir),
            headless=self._headless,
            channel=self._channel,
        ).info("Browser session started")

    async def aclose(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            self._context = None
            self._page = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            log.bind(provider=self._provider).info("Browser session closed")

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Acquire the session's single Page under a lock.

        Playwright's Page is not re-entrant; concurrent callers must serialize.
        """
        if self._context is None or self._page is None:
            await self.start()
        assert self._page is not None
        async with self._lock:
            yield self._page

    @asynccontextmanager
    async def raw_page(self) -> AsyncIterator[Page]:
        """Same as page() but without acquiring the lock.

        Use only from code that already holds the session lock OR from the
        login flow where no MCP tool calls run concurrently.
        """
        if self._context is None or self._page is None:
            await self.start()
        assert self._page is not None
        yield self._page
