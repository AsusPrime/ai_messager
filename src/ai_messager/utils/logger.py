from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger


_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | {message} | {extra}"
)
_STDERR_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> - <level>{message}</level> "
    "<dim>{extra}</dim>"
)


def setup_logger(
    logs_dir: Path,
    level: str = "INFO",
    *,
    stdio_server: bool = False,
) -> None:
    # In stdio_server mode stderr is muted: Claude Desktop captures stderr and
    # mixes it with the JSON-RPC framing diagnostics, which makes its log pane
    # noisy. File sink is enough — we tail it manually when debugging.
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()

    logger.add(
        logs_dir / "ai_messager.log",
        level=level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        format=_FILE_FORMAT,
    )

    if not stdio_server:
        logger.add(
            sys.stderr,
            level=level,
            enqueue=True,
            colorize=True,
            backtrace=True,
            diagnose=False,
            format=_STDERR_FORMAT,
        )


def get_logger(name: str) -> Logger:
    return logger.bind(name=name)
