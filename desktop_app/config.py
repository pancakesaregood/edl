"""Configuration helpers for the local EDL desktop tool."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    default_repo_path: str = ""
    theme: str = "flatly"
    ignore_comments_by_default: bool = True
    gitlab_username: str = "oauth2"


def config_path() -> Path:
    return Path(__file__).with_name("app_config.json")


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return AppConfig()

    return AppConfig(
        default_repo_path=str(data.get("default_repo_path", "")),
        theme=str(data.get("theme", "flatly")),
        ignore_comments_by_default=bool(data.get("ignore_comments_by_default", True)),
        gitlab_username=str(data.get("gitlab_username", "oauth2")),
    )


def save_config(config: AppConfig) -> None:
    payload = {
        "default_repo_path": config.default_repo_path,
        "theme": config.theme,
        "ignore_comments_by_default": config.ignore_comments_by_default,
        "gitlab_username": config.gitlab_username,
    }
    config_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
