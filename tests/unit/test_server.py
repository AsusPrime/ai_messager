from __future__ import annotations

from pathlib import Path

import pytest

from ai_messager.bridges.registry import build_default_registry
from ai_messager.core.config import AppConfig, EndpointConfig, Settings
from ai_messager.server import MCPServer


def _settings(tmp_path: Path) -> Settings:
    # Point every path into the tmp dir so tests cannot touch ~/.ai_messager.
    return Settings(
        profiles_dir=tmp_path / "profiles",
        config_path=tmp_path / "config.yaml",
        logs_dir=tmp_path / "logs",
        responses_dir=tmp_path / "responses",
    )


@pytest.mark.asyncio
async def test_mcp_server_registers_one_tool_per_endpoint(tmp_path: Path) -> None:
    cfg = AppConfig(
        endpoints=[
            EndpointConfig(
                name="gpt_architect",
                provider="chatgpt_web",
                chat_url="https://chatgpt.com/c/abc",
                description="Architect with memory.",
            ),
            EndpointConfig(
                name="gpt_fresh",
                provider="chatgpt_web",
                description="Stateless GPT.",
            ),
        ]
    )
    mcp = MCPServer(_settings(tmp_path), cfg, build_default_registry())
    try:
        # The decorator stashes the handler in the server's request_handlers.
        # We invoke it through the public list_tools endpoint instead.
        tools = await mcp.server.request_handlers[
            # mcp.types.ListToolsRequest is the key
            _list_tools_request_type()
        ](_list_tools_request_instance())
        names = sorted(t.name for t in tools.root.tools)
        assert names == ["ask_gpt_architect", "ask_gpt_fresh"]
    finally:
        await mcp.aclose()


def test_ask_tool_schema_shape() -> None:
    schema = MCPServer.ASK_TOOL_SCHEMA
    assert schema["type"] == "object"
    assert schema["required"] == ["message"]
    assert schema["properties"]["message"]["type"] == "string"
    assert schema["additionalProperties"] is False


def test_spill_reply_writes_file_and_returns_path(tmp_path: Path) -> None:
    reply = "x" * 12_000
    path = MCPServer._spill_reply(
        reply, tool="ask_gpt_architect", responses_dir=tmp_path
    )
    assert path.exists()
    assert path.parent == tmp_path
    assert path.read_text(encoding="utf-8") == reply
    assert path.suffix == ".md"
    assert "ask_gpt_architect" in path.name


def test_spill_reply_sanitizes_tool_names_with_slashes(tmp_path: Path) -> None:
    path = MCPServer._spill_reply("hi", tool="bad/name", responses_dir=tmp_path)
    assert "/" not in path.name.removesuffix(".md").split("_", 1)[1]


# --- helpers that isolate the mcp-internal types, so the main test body
# stays readable if the SDK reshapes its request types later.


def _list_tools_request_type():
    from mcp.types import ListToolsRequest

    return ListToolsRequest


def _list_tools_request_instance():
    from mcp.types import ListToolsRequest

    return ListToolsRequest(method="tools/list")
