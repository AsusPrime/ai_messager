from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ai_messager.core.config import AppConfig, load_app_config


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_load_minimal_config(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "endpoints": [
                {
                    "name": "gpt_fresh",
                    "provider": "chatgpt_web",
                    "description": "stateless gpt",
                }
            ]
        },
    )
    cfg = load_app_config(path)
    assert isinstance(cfg, AppConfig)
    assert len(cfg.endpoints) == 1
    ep = cfg.endpoints[0]
    assert ep.name == "gpt_fresh"
    assert ep.provider == "chatgpt_web"
    assert ep.chat_url is None


def test_load_pinned_chat(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "endpoints": [
                {
                    "name": "gpt_architect",
                    "provider": "chatgpt_web",
                    "chat_url": "https://chatgpt.com/c/abc-123",
                    "description": "architecture expert",
                }
            ]
        },
    )
    cfg = load_app_config(path)
    assert str(cfg.endpoints[0].chat_url) == "https://chatgpt.com/c/abc-123"


def test_duplicate_endpoint_names_rejected(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "endpoints": [
                {"name": "a", "provider": "chatgpt_web", "description": "x"},
                {"name": "a", "provider": "chatgpt_web", "description": "y"},
            ]
        },
    )
    with pytest.raises(ValidationError) as exc_info:
        load_app_config(path)
    assert "duplicate" in str(exc_info.value).lower()


def test_invalid_endpoint_name_rejected(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "endpoints": [
                {"name": "Bad-Name", "provider": "chatgpt_web", "description": "x"},
            ]
        },
    )
    with pytest.raises(ValidationError):
        load_app_config(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_app_config(tmp_path / "does_not_exist.yaml")


def test_unknown_provider_rejected(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "endpoints": [
                {"name": "x", "provider": "gemini_web", "description": "y"},
            ]
        },
    )
    with pytest.raises(ValidationError):
        load_app_config(path)
