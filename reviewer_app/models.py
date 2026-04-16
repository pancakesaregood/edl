"""Data models for reviewer desktop app."""

from __future__ import annotations

from dataclasses import dataclass, field


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
class ScriptAvailability:
    validate: bool = False
    build_release: bool = False
    publish_release: bool = False
    missing: list[str] = field(default_factory=list)


@dataclass
class LockInfo:
    file_name: str
    locked_by: str
    machine: str
    ticket: str
    timestamp: str


@dataclass
class ReviewDecision:
    filename: str
    ticket: str
    decision: str
    reviewer: str
    timestamp: str
    notes: str
    source_branch: str
    latest_commit_hash: str
    base_ref: str
    validation_ok: bool


@dataclass
class ReviewFileItem:
    rel_path: str
    name: str
    status: str
    lock: LockInfo | None = None
    validation_ok: bool | None = None
    validation_summary: str = ""
    decision: ReviewDecision | None = None
    ready_for_release: bool = False
