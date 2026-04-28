from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["chatgpt_web"]


class EndpointConfig(BaseModel):
    name: str = Field(
        ...,
        description="Unique endpoint name. Becomes the MCP tool name as 'ask_<name>'.",
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    provider: ProviderName = Field(
        ...,
        description="Which LLMBridge implementation to use.",
    )
    chat_url: HttpUrl | None = Field(
        default=None,
        description="If set, every call lands in this specific chat. If None, a fresh chat per call.",
    )
    description: str = Field(
        ...,
        description="Tool description shown to Claude. Make it specific — Claude uses it to pick the tool.",
        min_length=1,
    )


class AppConfig(BaseModel):
    endpoints: list[EndpointConfig]

    @field_validator("endpoints")
    @classmethod
    def _unique_names(cls, eps: list[EndpointConfig]) -> list[EndpointConfig]:
        seen: set[str] = set()
        for ep in eps:
            if ep.name in seen:
                raise ValueError(f"Duplicate endpoint name: {ep.name!r}")
            seen.add(ep.name)
        return eps


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_MESSAGER_",
        env_file=".env",
        extra="ignore",
    )

    profiles_dir: Path = Field(
        default_factory=lambda: Path.home() / ".ai_messager" / "profiles"
    )
    config_path: Path = Field(
        default_factory=lambda: Path.home() / ".ai_messager" / "config.yaml"
    )
    logs_dir: Path = Field(
        default_factory=lambda: Path.home() / ".ai_messager" / "logs"
    )
    responses_dir: Path = Field(
        default_factory=lambda: Path.home() / ".ai_messager" / "responses"
    )
    screenshots_dir: Path = Field(
        default_factory=lambda: Path.home() / ".ai_messager" / "screenshots"
    )

    response_overflow_chars: int = 10_000
    # Preview slice returned inline when a reply spills to a file.
    response_overflow_preview_chars: int = 500
    response_timeout_s: int = 120
    login_poll_interval_s: float = 2.0
    login_settle_s: float = 3.0
    login_max_wait_s: int = 300

    # How long to wait for composer / new-turn DOM events. Bump on slow
    # networks or when ChatGPT's UI is laggy.
    ui_ready_timeout_ms: int = 30_000
    # Stream end-detection: poll the assistant turn every poll_ms; consider
    # generation done when its text hasn't changed for stable_ms.
    # 4000ms is the FALLBACK window — the primary signal is the appearance
    # of a per-turn action button. The fallback only fires if testids drift,
    # so a generous window costs nothing in the happy path.
    stream_poll_ms: int = 300
    stream_stable_ms: int = 4000

    # "chrome" drives the user's installed Google Chrome (faster, better for OAuth flows).
    # Set to "chromium" (or "msedge") if Chrome is not installed.
    browser_channel: str = "chrome"

    # Headless when the MCP server runs. Set AI_MESSAGER_SERVE_HEADLESS=false
    # to get a visible Chrome window — useful for debugging ChatGPT UI issues
    # that only happen in headless (Cloudflare fingerprinting, layout differences).
    serve_headless: bool = True

    # Debug flag. Currently gates: spill-to-file for oversized replies.
    # When false (default), every reply is returned inline regardless of size.
    # When true, replies over `response_overflow_chars` are written to
    # `responses_dir` and only a preview + path is returned to Claude.
    debug: bool = False

    log_level: str = "INFO"

    def profile_dir_for(self, provider: str) -> Path:
        return self.profiles_dir / provider


def load_app_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found at {path}. Copy config.example.yaml there and edit."
        )
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Config at {path} must be a YAML mapping at top level.")
    return AppConfig.model_validate(raw)
