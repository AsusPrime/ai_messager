from __future__ import annotations

from pathlib import Path

from ai_messager.browser.session import BrowserSession


class BrowserManager:
    """Lazily creates one BrowserSession per provider.

    Multiple endpoints that share a provider share the same session (and lock).
    """

    def __init__(
        self,
        profiles_dir: Path,
        *,
        headless: bool = True,
        channel: str | None = "chrome",
    ) -> None:
        self._profiles_dir = profiles_dir
        self._headless = headless
        self._channel = channel
        self._sessions: dict[str, BrowserSession] = {}

    def get(self, provider: str) -> BrowserSession:
        if provider not in self._sessions:
            self._sessions[provider] = BrowserSession(
                provider=provider,
                user_data_dir=self._profiles_dir / provider,
                headless=self._headless,
                channel=self._channel,
            )
        return self._sessions[provider]

    async def aclose(self) -> None:
        for session in self._sessions.values():
            await session.aclose()
        self._sessions.clear()
