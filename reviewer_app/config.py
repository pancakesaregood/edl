"""Configuration helpers for the reviewer desktop app."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReviewerConfig:
    default_repo_path: str = ""
    theme: str = "flatly"
    default_base_ref: str = "origin/main"
    ignore_comments_by_default: bool = True


def config_path() -> Path:
    return Path(__file__).with_name("app_config.json")


def load_config() -> ReviewerConfig:
    path = config_path()
    if not path.exists():
        return ReviewerConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ReviewerConfig()

    return ReviewerConfig(
        default_repo_path=str(data.get("default_repo_path", "")),
        theme=str(data.get("theme", "flatly")),
        default_base_ref=str(data.get("default_base_ref", "origin/main")),
        ignore_comments_by_default=bool(data.get("ignore_comments_by_default", True)),
    )


def save_config(config: ReviewerConfig) -> None:
    payload = {
        "default_repo_path": config.default_repo_path,
        "theme": config.theme,
        "default_base_ref": config.default_base_ref,
        "ignore_comments_by_default": config.ignore_comments_by_default,
    }
    config_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
