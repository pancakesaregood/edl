"""Review decision persistence for reviewer sign-off workflow."""

from __future__ import annotations

import json
from pathlib import Path

from .models import ReviewDecision


class ReviewStore:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()
        self.root = self.repo_path / "review-decisions"
        self.root.mkdir(parents=True, exist_ok=True)

    def _slug(self, rel_path: str) -> str:
        safe = rel_path.replace("\\", "__").replace("/", "__")
        safe = safe.replace(":", "_")
        return safe

    def decision_path(self, rel_path: str) -> Path:
        return self.root / f"{self._slug(rel_path)}.json"

    def load(self, rel_path: str) -> ReviewDecision | None:
        path = self.decision_path(rel_path)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return ReviewDecision(
                filename=str(data.get("filename", rel_path)),
                ticket=str(data.get("ticket", "")),
                decision=str(data.get("decision", "")).lower(),
                reviewer=str(data.get("reviewer", "")),
                timestamp=str(data.get("timestamp", "")),
                notes=str(data.get("notes", "")),
                source_branch=str(data.get("source_branch", "")),
                latest_commit_hash=str(data.get("latest_commit_hash", "")),
                base_ref=str(data.get("base_ref", "")),
                validation_ok=bool(data.get("validation_ok", False)),
            )
        except Exception:
            return None

    def save(self, record: ReviewDecision) -> Path:
        path = self.decision_path(record.filename)
        payload = {
            "filename": record.filename,
            "ticket": record.ticket,
            "decision": record.decision,
            "reviewer": record.reviewer,
            "timestamp": record.timestamp,
            "notes": record.notes,
            "source_branch": record.source_branch,
            "latest_commit_hash": record.latest_commit_hash,
            "base_ref": record.base_ref,
            "validation_ok": record.validation_ok,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def list_all(self) -> list[ReviewDecision]:
        records: list[ReviewDecision] = []
        if not self.root.exists():
            return records

        for path in sorted(self.root.glob("*.json"), key=lambda p: p.name.lower()):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                records.append(
                    ReviewDecision(
                        filename=str(data.get("filename", "")),
                        ticket=str(data.get("ticket", "")),
                        decision=str(data.get("decision", "")).lower(),
                        reviewer=str(data.get("reviewer", "")),
                        timestamp=str(data.get("timestamp", "")),
                        notes=str(data.get("notes", "")),
                        source_branch=str(data.get("source_branch", "")),
                        latest_commit_hash=str(data.get("latest_commit_hash", "")),
                        base_ref=str(data.get("base_ref", "")),
                        validation_ok=bool(data.get("validation_ok", False)),
                    )
                )
            except Exception:
                continue

        return records
