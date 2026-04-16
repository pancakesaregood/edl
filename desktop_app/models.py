"""Domain models for EDL desktop app state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def command_display(self) -> str:
        return " ".join(self.command)


@dataclass
class LockInfo:
    file_name: str
    locked_by: str
    machine: str
    ticket: str
    timestamp: str


@dataclass
class FileItem:
    name: str
    path: Path
    status: str = "available"
    lock: LockInfo | None = None
    validation_failed: bool = False
    modified: bool = False


@dataclass
class ScriptAvailability:
    checkout: bool = False
    validate: bool = False
    checkin: bool = False
    build_release: bool = False
    publish_release: bool = False
    missing: list[str] = field(default_factory=list)
