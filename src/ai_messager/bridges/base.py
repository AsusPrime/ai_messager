from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ai_messager.browser.session import BrowserSession
    from ai_messager.core.config import Settings


class LLMBridge(ABC):
    """One implementation per web LLM provider.

    Subclasses declare three class-level constants and implement two async methods.
    BrowserSession is injected — the bridge never owns the Playwright lifecycle.
    """

    provider_name: ClassVar[str]
    home_url: ClassVar[str]
    default_chat_path: ClassVar[str]

    # OAuth/CDN domains a login flow should probe for session cookies.
    # Each subclass overrides with the hops users get redirected through.
    diagnostic_cookie_domains: ClassVar[tuple[str, ...]] = ()

    def __init__(self, session: BrowserSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    @abstractmethod
    async def is_logged_in(self, page: Page) -> bool:
        """Return True if the current session has a valid login for this provider."""

    @abstractmethod
    async def ask(self, message: str, chat_url: str | None) -> str:
        """Send a message; return the assistant's reply text.

        If chat_url is None the bridge must start/continue a fresh chat.
        If chat_url is set the bridge must navigate to that specific conversation.
        """
