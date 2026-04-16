"""Repository and command helpers for reviewer desktop app."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
from pathlib import Path

from .models import CommandResult, LockInfo, ScriptAvailability


class ReviewerRepoService:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()

    @property
    def working_dir(self) -> Path:
        return self.repo_path / "edl" / "working"

    @property
    def approved_dir(self) -> Path:
        return self.repo_path / "edl" / "approved"

    @property
    def locks_dir(self) -> Path:
        return self.repo_path / "locks"

    @property
    def scripts_dir(self) -> Path:
        return self.repo_path / "scripts"

    @property
    def releases_dir(self) -> Path:
        return self.repo_path / "edl" / "releases"

    def validate_structure(self) -> tuple[bool, str]:
        required = [
            self.working_dir,
            self.approved_dir,
            self.locks_dir,
            self.scripts_dir,
            self.releases_dir,
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            return False, "Missing required folders:\n" + "\n".join(missing)
        return True, ""

    def detect_scripts(self) -> ScriptAvailability:
        mapping = {
            "validate": self.scripts_dir / "validate.ps1",
            "build_release": self.scripts_dir / "build-release.ps1",
            "publish_release": self.scripts_dir / "publish-release.ps1",
        }

        availability = ScriptAvailability()
        missing: list[str] = []
        for key, path in mapping.items():
            present = path.exists()
            setattr(availability, key, present)
            if not present:
                missing.append(path.name)

        availability.missing = missing
        return availability

    def run_command(self, command: list[str], timeout: int = 180) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo_path),
                text=True,
                capture_output=True,
                shell=False,
                timeout=timeout,
            )
            return CommandResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except FileNotFoundError as exc:
            return CommandResult(command=command, returncode=1, stdout="", stderr=f"Executable not found: {exc}")
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                returncode=1,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\nCommand timed out.",
            )
        except Exception as exc:
            return CommandResult(command=command, returncode=1, stdout="", stderr=str(exc))

    def run_powershell_script(self, script_name: str, args: list[str]) -> CommandResult:
        script_path = self.scripts_dir / script_name
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *args,
        ]
        return self.run_command(command)

    def git_command(self, *args: str) -> CommandResult:
        return self.run_command(["git", *args])

    def git_available(self) -> bool:
        result = self.git_command("rev-parse", "--is-inside-work-tree")
        return result.ok and result.stdout.strip().lower() == "true"

    def git_branch(self) -> str:
        result = self.git_command("rev-parse", "--abbrev-ref", "HEAD")
        if result.ok:
            return result.stdout.strip()
        return "(not a git repo)"

    def current_commit(self) -> str:
        result = self.git_command("rev-parse", "HEAD")
        if result.ok:
            return result.stdout.strip()
        return ""

    def git_user(self) -> str:
        result = self.git_command("config", "user.name")
        if result.ok and result.stdout.strip():
            return result.stdout.strip()
        return os.environ.get("USERNAME", "unknown")

    def git_status_summary(self) -> str:
        result = self.git_command("status", "--porcelain")
        if not result.ok:
            return "git status unavailable"

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "working tree clean"

        staged = 0
        unstaged = 0
        untracked = 0
        for line in lines:
            if line.startswith("??"):
                untracked += 1
                continue
            if len(line) >= 2:
                if line[0] != " ":
                    staged += 1
                if line[1] != " ":
                    unstaged += 1

        return f"changes: staged={staged}, unstaged={unstaged}, untracked={untracked}"

    def fetch_latest(self) -> CommandResult:
        return self.git_command("fetch", "--all", "--prune")

    def ref_exists(self, ref: str) -> bool:
        result = self.git_command("rev-parse", "--verify", ref)
        return result.ok

    def resolve_base_ref(self, preferred: str = "origin/main") -> str:
        candidates = [preferred, "origin/main", "origin/master", "main", "master"]
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate and self.ref_exists(candidate):
                return candidate

        return "HEAD"

    def parse_porcelain_paths(self, porcelain_output: str) -> list[str]:
        paths: list[str] = []
        for raw in porcelain_output.splitlines():
            line = raw.rstrip()
            if len(line) < 4:
                continue
            payload = line[3:]
            if " -> " in payload:
                payload = payload.split(" -> ", 1)[1]
            paths.append(payload.replace("\\", "/"))
        return paths

    def changed_review_files(self, base_ref: str) -> list[str]:
        collected: set[str] = set()

        if base_ref and base_ref != "HEAD":
            committed_diff = self.git_command("diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD")
            if committed_diff.ok:
                for line in committed_diff.stdout.splitlines():
                    rel = line.strip().replace("\\", "/")
                    if rel:
                        collected.add(rel)

        status_result = self.git_command("status", "--porcelain")
        if status_result.ok:
            for rel in self.parse_porcelain_paths(status_result.stdout):
                collected.add(rel)

        filtered = [
            rel for rel in collected
            if rel.startswith("edl/working/") and rel.lower().endswith(".txt")
        ]
        return sorted(filtered, key=str.lower)

    def read_working_file(self, rel_path: str) -> str:
        full_path = (self.repo_path / rel_path).resolve()
        working_root = self.working_dir.resolve()
        try:
            full_path.relative_to(working_root)
        except ValueError as exc:
            raise ValueError("Can only read files under edl/working.") from exc

        if not full_path.exists():
            return ""
        return full_path.read_text(encoding="utf-8")

    def read_file_from_ref(self, ref: str, rel_path: str) -> str:
        target = f"{ref}:{rel_path}"
        result = self.git_command("show", target)
        if result.ok:
            return result.stdout
        return ""

    def unified_diff(self, baseline: str, proposed: str, rel_path: str) -> str:
        base_lines = baseline.splitlines()
        new_lines = proposed.splitlines()
        diff_lines = difflib.unified_diff(
            base_lines,
            new_lines,
            fromfile=f"{rel_path} (baseline)",
            tofile=f"{rel_path} (proposed)",
            lineterm="",
        )
        return "\n".join(diff_lines)

    def duplicate_lines(self, content: str) -> list[str]:
        seen: dict[str, int] = {}
        duplicates: list[str] = []
        for line in content.splitlines():
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue
            key = trimmed.lower()
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 2:
                duplicates.append(trimmed)
        return duplicates

    def load_locks(self) -> dict[str, LockInfo]:
        locks: dict[str, LockInfo] = {}
        if not self.locks_dir.exists():
            return locks

        for lock_path in self.locks_dir.glob("*.lock.json"):
            try:
                payload = json.loads(lock_path.read_text(encoding="utf-8-sig"))
                file_name = str(payload.get("file_name", "")).strip()
                if not file_name:
                    continue
                file_key = Path(file_name).name
                locks[file_key] = LockInfo(
                    file_name=file_name,
                    locked_by=str(payload.get("locked_by", "")).strip(),
                    machine=str(payload.get("machine", "")).strip(),
                    ticket=str(payload.get("ticket", "")).strip(),
                    timestamp=str(payload.get("timestamp", "")).strip(),
                )
            except Exception:
                continue

        return locks

    def lock_for_rel_path(self, rel_path: str) -> LockInfo | None:
        return self.load_locks().get(Path(rel_path).name)

    def run_validation(self, rel_path: str, ignore_comments: bool = True) -> CommandResult:
        args = ["-Path", str(self.repo_path / rel_path)]
        if ignore_comments:
            args.append("-IgnoreComments")
        return self.run_powershell_script("validate.ps1", args)

    def summarize_validation(self, result: CommandResult) -> str:
        if result.ok:
            for line in reversed(result.stdout.splitlines()):
                text = line.strip()
                if text:
                    return text
            return "Validation succeeded."

        merged = (result.stderr + "\n" + result.stdout).strip()
        if not merged:
            return "Validation failed."

        first = merged.splitlines()[0].strip()
        return first or "Validation failed."

    def approved_matches_working(self, rel_path: str) -> bool:
        file_name = Path(rel_path).name
        working_path = self.working_dir / file_name
        approved_path = self.approved_dir / file_name

        if not working_path.exists() or not approved_path.exists():
            return False

        return working_path.read_bytes() == approved_path.read_bytes()

    def promote_to_approved(self, rel_path: str) -> None:
        file_name = Path(rel_path).name
        source = (self.working_dir / file_name).resolve()
        target = (self.approved_dir / file_name).resolve()

        working_root = self.working_dir.resolve()
        approved_root = self.approved_dir.resolve()

        try:
            source.relative_to(working_root)
            target.relative_to(approved_root)
        except ValueError as exc:
            raise ValueError("Promotion paths are outside allowed folders.") from exc

        if not source.exists():
            raise FileNotFoundError(f"Working file not found: {source}")

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    def release_ids(self) -> list[str]:
        archive = self.releases_dir / "archive"
        if not archive.exists():
            return []
        return sorted([p.name for p in archive.iterdir() if p.is_dir()], key=str.lower)

    def build_release(self, release_id: str | None = None) -> CommandResult:
        args: list[str] = []
        if release_id:
            args.extend(["-ReleaseId", release_id])
        return self.run_powershell_script("build-release.ps1", args)

    def publish_release(self, release_id: str, destination: str = "", dry_run: bool = True) -> CommandResult:
        args: list[str] = ["-ReleaseId", release_id]
        if destination:
            args.extend(["-DestinationPath", destination])
        if dry_run:
            args.append("-DryRun")
        return self.run_powershell_script("publish-release.ps1", args)
