"""MCP stdio server exposing one ask_* tool per configured endpoint."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from ai_messager.bridges.base import LLMBridge
from ai_messager.bridges.registry import BridgeRegistry
from ai_messager.browser.manager import BrowserManager
from ai_messager.core.config import AppConfig, EndpointConfig, Settings
from ai_messager.core.exceptions import AIMessagerError
from ai_messager.utils.logger import get_logger

log = get_logger(__name__)


class MCPServer:
    """Wires bridges → BrowserManager → MCP Server and runs the stdio loop."""

    # Keep the tool signature minimal: only `message`. Chat binding lives in
    # config, not in runtime args — Claude chooses the right tool *name*.
    ASK_TOOL_SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message to send to the LLM.",
            },
        },
        "required": ["message"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        settings: Settings,
        config: AppConfig,
        registry: BridgeRegistry,
    ) -> None:
        self._settings = settings
        self._config = config
        self._registry = registry
        self._endpoints: dict[str, EndpointConfig] = {
            ep.name: ep for ep in config.endpoints
        }
        self._ordered_endpoints: list[EndpointConfig] = list(config.endpoints)

        self._manager = BrowserManager(
            profiles_dir=settings.profiles_dir,
            headless=settings.serve_headless,
            channel=settings.browser_channel,
        )
        self._bridges: dict[str, LLMBridge] = {}
        self._build_bridges()

        self._server: Server = Server("ai-messager")
        self._wire_handlers()

    @property
    def server(self) -> Server:
        return self._server

    def _build_bridges(self) -> None:
        # One bridge per unique provider. Endpoints sharing a provider share
        # the same bridge instance and thus the same BrowserSession + lock.
        providers = {ep.provider for ep in self._config.endpoints}
        for provider in providers:
            bridge_cls = self._registry.get(provider)
            session = self._manager.get(provider)
            self._bridges[provider] = bridge_cls(session, self._settings)

    def _wire_handlers(self) -> None:
        @self._server.list_tools()
        async def _list_tools() -> list[Tool]:
            return [self._tool_for(ep) for ep in self._ordered_endpoints]

        @self._server.call_tool()
        async def _call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            return await self._handle_call(name, arguments)

    @staticmethod
    def _tool_for(endpoint: EndpointConfig) -> Tool:
        return Tool(
            name=f"ask_{endpoint.name}",
            description=endpoint.description.strip(),
            inputSchema=MCPServer.ASK_TOOL_SCHEMA,
        )

    async def _handle_call(
        self, name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        args = arguments or {}
        if not name.startswith("ask_"):
            raise ValueError(f"Unknown tool: {name}")
        ep_name = name.removeprefix("ask_")
        ep = self._endpoints.get(ep_name)
        if ep is None:
            raise ValueError(f"Unknown tool: {name}")
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Argument 'message' must be a non-empty string.")
        bridge = self._bridges[ep.provider]
        log.bind(tool=name, provider=ep.provider).info("Tool call start")
        try:
            reply = await bridge.ask(message, str(ep.chat_url) if ep.chat_url else None)
        except AIMessagerError as exc:
            log.bind(
                tool=name,
                provider=ep.provider,
                error_type=type(exc).__name__,
                error=str(exc),
            ).error("Bridge error")
            raise
        # First 500 chars so we can tell whether a surprise reply comes
        # from GPT itself (genuine answer) or from our extractor picking
        # up the wrong DOM node (old turn, placeholder, toolbar text).
        log.bind(
            tool=name,
            provider=ep.provider,
            reply_chars=len(reply),
            reply_preview=reply[:500],
        ).info("Tool call done")

        # Overflow policy: off by default — replies are returned inline
        # regardless of length. When AI_MESSAGER_DEBUG=true, replies larger
        # than response_overflow_chars get written to disk and Claude gets a
        # preview + path. Useful for diagnosing long-reply content without
        # flooding the main conversation.
        if self._settings.debug and len(reply) > self._settings.response_overflow_chars:
            path = self._spill_reply(
                reply, tool=name, responses_dir=self._settings.responses_dir
            )
            preview_chars = self._settings.response_overflow_preview_chars
            log.bind(
                tool=name,
                path=str(path),
                reply_chars=len(reply),
                threshold=self._settings.response_overflow_chars,
            ).info("Reply spilled to disk")
            payload = (
                f"Response too large: {len(reply)} chars "
                f"(threshold {self._settings.response_overflow_chars}).\n"
                f"Saved to: {path}\n"
                f"Use your Read tool on that path for the full text "
                f"(supports offset/limit for partial reads).\n\n"
                f"--- preview (first {preview_chars} chars) ---\n"
                f"{reply[:preview_chars]}\n"
            )
            return [TextContent(type="text", text=payload)]

        return [TextContent(type="text", text=reply)]

    @staticmethod
    def _spill_reply(reply: str, *, tool: str, responses_dir: Path) -> Path:
        """Write an oversized reply to a timestamped markdown file and return the path."""
        responses_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        safe_tool = tool.replace("/", "_")
        path = responses_dir / f"{ts}_{safe_tool}.md"
        path.write_text(reply, encoding="utf-8")
        return path

    async def run(self) -> None:
        """Run the MCP server on stdio until the client disconnects."""
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self._server.run(
                    read_stream,
                    write_stream,
                    self._server.create_initialization_options(),
                )
        finally:
            await self._manager.aclose()

    async def aclose(self) -> None:
        await self._manager.aclose()
