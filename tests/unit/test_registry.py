from __future__ import annotations

import pytest

from ai_messager.bridges.chatgpt_web import ChatGPTBridge
from ai_messager.bridges.registry import build_default_registry
from ai_messager.core.exceptions import ProviderNotRegistered


def test_chatgpt_provider_registered() -> None:
    registry = build_default_registry()
    assert "chatgpt_web" in registry.known()
    assert registry.get("chatgpt_web") is ChatGPTBridge


def test_unknown_provider_raises() -> None:
    registry = build_default_registry()
    with pytest.raises(ProviderNotRegistered) as exc_info:
        registry.get("gemini_web")
    assert "gemini_web" in str(exc_info.value)
