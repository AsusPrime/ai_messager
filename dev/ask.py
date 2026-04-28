"""Manual end-to-end test for a bridge's ask() flow.

Usage:
    uv run python dev/ask.py chatgpt_web "What is 2+2?"
    uv run python dev/ask.py chatgpt_web "..." --chat-url https://chatgpt.com/c/<id>
    uv run python dev/ask.py chatgpt_web "..." --headless

The script runs the exact same code path MCP will use, but prints the reply
to stdout instead of returning it to Claude. Useful when iterating on
selectors / timeouts without wiring up the full MCP server.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ai_messager.config import Settings
from ai_messager.logging_ import configure_logging

from ai_messager.bridges.registry import build_default_registry
from ai_messager.browser.session import BrowserSession


async def run(provider: str, message: str, chat_url: str | None, headless: bool) -> int:
    settings = Settings()
    configure_logging(settings.logs_dir, settings.log_level)

    bridge_cls = build_default_registry().get(provider)
    session = BrowserSession(
        provider=provider,
        user_data_dir=settings.profile_dir_for(provider),
        headless=headless,
        channel=settings.browser_channel,
    )
    await session.start()
    bridge = bridge_cls(session, settings)
    try:
        reply = await bridge.ask(message, chat_url)
        print("---- reply ----")
        print(reply)
        print("---- end ----")
        return 0
    finally:
        await session.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual ask() test harness.")
    parser.add_argument("provider", help="Provider name, e.g. chatgpt_web")
    parser.add_argument("message", help="Prompt to send")
    parser.add_argument(
        "--chat-url",
        default=None,
        help="Pinned chat URL. If omitted, a fresh chat is started.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a visible window. Default: visible (easier to debug).",
    )
    args = parser.parse_args()
    return asyncio.run(
        run(
            provider=args.provider,
            message=args.message,
            chat_url=args.chat_url,
            headless=args.headless,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
