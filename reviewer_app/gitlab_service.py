"""Minimal GitLab API client for reviewer approval workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, parse, request


@dataclass
class GitLabApiResult:
    ok: bool
    status_code: int
    payload: object | None
    error: str = ""


class GitLabService:
    def __init__(self, base_url: str, token: str, project_ref: str) -> None:
        self.base_url = self.normalize_base_url(base_url)
        self.token = token.strip()
        self.project_ref = project_ref.strip()

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        text = base_url.strip().rstrip("/")
        return text

    @staticmethod
    def derive_from_remote(remote_url: str) -> tuple[str, str]:
        text = remote_url.strip()
        if not text:
            return "", ""

        if text.startswith("http://") or text.startswith("https://"):
            parsed = parse.urlparse(text)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            path = parsed.path.rstrip("/")
            if path.endswith(".git"):
                path = path[:-4]
            project = path.lstrip("/")
            return base_url, project

        # git@host:group/project.git
        if "@" in text and ":" in text and text.startswith("git@"):
            try:
                host = text.split("@", 1)[1].split(":", 1)[0]
                path = text.split(":", 1)[1]
                if path.endswith(".git"):
                    path = path[:-4]
                return f"https://{host}", path.strip("/")
            except Exception:
                return "", ""

        # ssh://git@host/group/project.git
        if text.startswith("ssh://"):
            parsed = parse.urlparse(text)
            host = parsed.hostname or ""
            path = parsed.path.rstrip("/")
            if path.endswith(".git"):
                path = path[:-4]
            return (f"https://{host}" if host else ""), path.lstrip("/")

        return "", ""

    def is_configured(self) -> bool:
        return bool(self.base_url and self.token and self.project_ref)

    def _project_encoded(self) -> str:
        return parse.quote_plus(self.project_ref)

    def _parse_payload(self, raw: str) -> object | None:
        raw = raw.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def _error_message(self, payload: object | None, fallback: str) -> str:
        if isinstance(payload, dict) and "message" in payload:
            message = payload["message"]
            if isinstance(message, str):
                return message
            if isinstance(message, list):
                return "; ".join(str(part) for part in message)
            if isinstance(message, dict):
                parts: list[str] = []
                for key, value in message.items():
                    if isinstance(value, list):
                        parts.append(f"{key}: {', '.join(str(v) for v in value)}")
                    else:
                        parts.append(f"{key}: {value}")
                if parts:
                    return "; ".join(parts)
        if isinstance(payload, str) and payload:
            return payload
        return fallback

    def _request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> GitLabApiResult:
        if not self.base_url:
            return GitLabApiResult(ok=False, status_code=0, payload=None, error="GitLab base URL is not set.")
        if not self.token:
            return GitLabApiResult(ok=False, status_code=0, payload=None, error="GitLab token is not set.")

        query_text = ""
        if query:
            query_text = "?" + parse.urlencode(query)
        url = f"{self.base_url}{path}{query_text}"

        headers = {
            "PRIVATE-TOKEN": self.token,
            "Accept": "application/json",
            "User-Agent": "edl-reviewer-tool/1.0",
        }

        payload_bytes: bytes | None = None
        if body is not None:
            payload_bytes = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url=url, data=payload_bytes, headers=headers, method=method.upper())

        try:
            with request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                payload = self._parse_payload(raw)
                return GitLabApiResult(ok=True, status_code=resp.status, payload=payload, error="")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            payload = self._parse_payload(raw)
            message = self._error_message(payload, f"HTTP {exc.code}")
            return GitLabApiResult(ok=False, status_code=exc.code, payload=payload, error=message)
        except Exception as exc:
            return GitLabApiResult(ok=False, status_code=0, payload=None, error=str(exc))

    def whoami(self) -> GitLabApiResult:
        return self._request("GET", "/api/v4/user")

    def get_project(self) -> GitLabApiResult:
        return self._request("GET", f"/api/v4/projects/{self._project_encoded()}")

    def get_member(self, user_id: int, project_id: int) -> GitLabApiResult:
        return self._request("GET", f"/api/v4/projects/{project_id}/members/all/{user_id}")

    def list_merge_requests(
        self,
        project_id: int,
        reviewer_username: str = "",
        state: str = "opened",
    ) -> GitLabApiResult:
        query: dict[str, str] = {
            "state": state,
            "scope": "all",
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": "100",
        }
        if reviewer_username:
            query["reviewer_username"] = reviewer_username
        return self._request("GET", f"/api/v4/projects/{project_id}/merge_requests", query=query)

    def get_merge_request(self, project_id: int, mr_iid: int) -> GitLabApiResult:
        return self._request("GET", f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}")

    def approve_merge_request(self, project_id: int, mr_iid: int) -> GitLabApiResult:
        return self._request("POST", f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/approve")

    def unapprove_merge_request(self, project_id: int, mr_iid: int) -> GitLabApiResult:
        return self._request("POST", f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/unapprove")

    def add_merge_request_note(self, project_id: int, mr_iid: int, note: str) -> GitLabApiResult:
        return self._request(
            "POST",
            f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes",
            body={"body": note},
        )
