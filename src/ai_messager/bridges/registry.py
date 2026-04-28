from __future__ import annotations

from ai_messager.bridges.base import LLMBridge
from ai_messager.core.exceptions import ProviderNotRegistered


class BridgeRegistry:
    """Maps provider names (from config.yaml) to their bridge classes.

    No global state — each entrypoint constructs its own instance via
    ``build_default_registry()`` (or builds a custom one for tests / plugins).
    """

    def __init__(self) -> None:
        self._bridges: dict[str, type[LLMBridge]] = {}

    def register(self, bridge_cls: type[LLMBridge]) -> None:
        self._bridges[bridge_cls.provider_name] = bridge_cls

    def get(self, provider: str) -> type[LLMBridge]:
        try:
            return self._bridges[provider]
        except KeyError as exc:
            raise ProviderNotRegistered(provider, list(self._bridges)) from exc

    def known(self) -> list[str]:
        return list(self._bridges)


def build_default_registry() -> BridgeRegistry:
    """Production registry. Add new providers here as one-line registrations."""
    # Imported lazily so importing this module doesn't pull Playwright.
    from ai_messager.bridges.chatgpt_web import ChatGPTBridge

    registry = BridgeRegistry()
    registry.register(ChatGPTBridge)
    return registry
