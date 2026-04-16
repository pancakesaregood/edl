"""Repository and command execution helpers for EDL desktop app."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from .models import CommandResult, FileItem, LockInfo, ScriptAvailability


class RepoService:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()
        self._gitlab_username = "oauth2"
        self._gitlab_token = ""

    @property
    def working_dir(self) -> Path:
        return self.repo_path / "edl" / "working"

    @property
    def approved_dir(self) -> Path:
        return self.repo_path / "edl" / "approved"

    @property
    def releases_dir(self) -> Path:
        return self.repo_path / "edl" / "releases"

    @property
    def locks_dir(self) -> Path:
        return self.repo_path / "locks"

    @property
    def scripts_dir(self) -> Path:
        return self.repo_path / "scripts"

    def validate_structure(self) -> tuple[bool, str]:
        expected = [
            self.working_dir,
            self.approved_dir,
            self.releases_dir,
            self.locks_dir,
            self.scripts_dir,
        ]
        missing = [str(p) for p in expected if not p.exists()]
        if missing:
            return False, "Missing required folders:\n" + "\n".join(missing)
        return True, ""

    def detect_scripts(self) -> ScriptAvailability:
        mapping = {
            "checkout": self.scripts_dir / "checkout.ps1",
            "validate": self.scripts_dir / "validate.ps1",
            "checkin": self.scripts_dir / "checkin.ps1",
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

    def list_working_files(self) -> list[Path]:
        if not self.working_dir.exists():
            return []
        return sorted(self.working_dir.glob("*.txt"), key=lambda p: p.name.lower())

    def read_working_file(self, file_name: str) -> str:
        path = self.safe_working_file(file_name)
        return path.read_text(encoding="utf-8")

    def save_working_file(self, file_name: str, content: str) -> None:
        path = self.safe_working_file(file_name)
        path.write_text(content, encoding="utf-8")

    def safe_working_file(self, file_name: str) -> Path:
        candidate = (self.working_dir / file_name).resolve()
        working_root = self.working_dir.resolve()
        try:
            candidate.relative_to(working_root)
        except ValueError as exc:
            raise ValueError("Editing outside edl/working is not allowed.") from exc

        if candidate.suffix.lower() != ".txt":
            raise ValueError("Only .txt working files are supported.")
        return candidate

    def load_locks(self) -> dict[str, LockInfo]:
        locks: dict[str, LockInfo] = {}
        if not self.locks_dir.exists():
            return locks

        for lock_path in self.locks_dir.glob("*.lock.json"):
            try:
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                file_name = str(data.get("file_name", "")).strip()
                if not file_name:
                    continue
                lock = LockInfo(
                    file_name=file_name,
                    locked_by=str(data.get("locked_by", "")).strip(),
                    machine=str(data.get("machine", "")).strip(),
                    ticket=str(data.get("ticket", "")).strip(),
                    timestamp=str(data.get("timestamp", "")).strip(),
                )
                locks[file_name.replace("\\", "/")] = lock
            except Exception:
                # Keep UI resilient if one lock file is malformed.
                continue
        return locks

    def current_username(self) -> str:
        return os.environ.get("USERNAME", "unknown")

    def run_command(
        self,
        command: list[str],
        timeout: int = 120,
        env_extra: dict[str, str] | None = None,
    ) -> CommandResult:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo_path),
                text=True,
                capture_output=True,
                shell=False,
                timeout=timeout,
                env=env,
            )
            return CommandResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except FileNotFoundError as exc:
            return CommandResult(
                command=command,
                returncode=1,
                stdout="",
                stderr=f"Executable not found: {exc}",
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                returncode=1,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\nCommand timed out.",
            )
        except Exception as exc:
            return CommandResult(
                command=command,
                returncode=1,
                stdout="",
                stderr=str(exc),
            )

    def run_powershell_script(self, script_name: str, args: Iterable[str]) -> CommandResult:
        script_path = self.scripts_dir / script_name
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *list(args),
        ]
        return self.run_command(command)

    def git_command(self, *args: str) -> CommandResult:
        return self.run_command(["git", *args])

    def set_gitlab_auth(self, username: str, token: str) -> None:
        self._gitlab_username = username.strip() or "oauth2"
        self._gitlab_token = token.strip()

    def gitlab_token_configured(self) -> bool:
        return bool(self._effective_gitlab_token())

    def git_origin_url(self) -> str:
        result = self.git_command("remote", "get-url", "origin")
        if result.ok:
            return result.stdout.strip()
        return ""

    def git_origin_uses_http(self) -> bool:
        url = self.git_origin_url().lower()
        return url.startswith("http://") or url.startswith("https://")

    def git_push_branch(self, branch: str) -> CommandResult:
        return self._git_network_command("push", "-u", "origin", branch)

    def _effective_gitlab_token(self) -> str:
        configured = self._gitlab_token.strip()
        if configured:
            return configured
        return os.environ.get("GITLAB_TOKEN", "").strip()

    def _create_askpass_script(self) -> Path:
        script_text = (
            "@echo off\r\n"
            "setlocal\r\n"
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "
            "\"$promptText = $args -join ' '; "
            "if ($promptText -match '(?i)username') { [Console]::Out.Write($env:GITLAB_AUTH_USERNAME) } "
            "else { [Console]::Out.Write($env:GITLAB_AUTH_TOKEN) }\" -- %*\r\n"
        )

        fd, temp_path = tempfile.mkstemp(prefix="edl-git-askpass-", suffix=".cmd")
        os.close(fd)
        path = Path(temp_path)
        path.write_text(script_text, encoding="utf-8")
        return path

    def _git_network_command(self, *args: str) -> CommandResult:
        token = self._effective_gitlab_token()
        env_extra: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
        askpass_path: Path | None = None

        if token:
            askpass_path = self._create_askpass_script()
            env_extra["GIT_ASKPASS"] = str(askpass_path)
            env_extra["GITLAB_AUTH_USERNAME"] = self._gitlab_username
            env_extra["GITLAB_AUTH_TOKEN"] = token

        try:
            return self.run_command(["git", *args], timeout=180, env_extra=env_extra)
        finally:
            if askpass_path is not None:
                try:
                    askpass_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def git_available(self) -> bool:
        result = self.git_command("rev-parse", "--is-inside-work-tree")
        return result.ok and result.stdout.strip().lower() == "true"

    def git_branch(self) -> str:
        result = self.git_command("rev-parse", "--abbrev-ref", "HEAD")
        if result.ok:
            return result.stdout.strip()
        return "(not a git repo)"

    def git_user(self) -> str:
        result = self.git_command("config", "user.name")
        if result.ok and result.stdout.strip():
            return result.stdout.strip()
        return self.current_username()

    def git_changed_files(self) -> list[str]:
        result = self.git_command("status", "--porcelain")
        if not result.ok:
            return []

        paths: list[str] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.rstrip()
            if len(line) < 4:
                continue
            payload = line[3:]
            if " -> " in payload:
                payload = payload.split(" -> ", 1)[1]
            paths.append(payload)
        return paths

    def file_items(
        self,
        validation_failures: set[str],
        search: str = "",
    ) -> list[FileItem]:
        locks = self.load_locks()
        changed = {entry.replace("\\", "/") for entry in self.git_changed_files()}
        user = self.current_username().lower()
        filtered = search.strip().lower()

        items: list[FileItem] = []
        for path in self.list_working_files():
            rel_key = path.name
            if filtered and filtered not in rel_key.lower():
                continue

            lock = locks.get(rel_key) or locks.get(rel_key.replace("\\", "/"))
            modified = (
                f"edl/working/{rel_key}" in changed
                or rel_key in changed
            )
            failed = rel_key in validation_failures

            status = "available"
            if failed:
                status = "validation failed"
            elif lock and lock.locked_by.lower() != user:
                status = "checked out by someone else"
            elif lock and lock.locked_by.lower() == user:
                status = "checked out by me"
            elif modified:
                status = "modified"

            items.append(
                FileItem(
                    name=rel_key,
                    path=path,
                    status=status,
                    lock=lock,
                    validation_failed=failed,
                    modified=modified,
                )
            )

        return items

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
