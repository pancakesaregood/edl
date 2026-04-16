"""Reviewer desktop UI for EDL sign-off workflow."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import platform
import socket
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

try:
    import ttkbootstrap as ttkbootstrap  # type: ignore

    HAS_TTKBOOTSTRAP = True
    ttk = ttkbootstrap
except Exception:
    from tkinter import ttk  # type: ignore

    HAS_TTKBOOTSTRAP = False
    ttkbootstrap = None

from .config import ReviewerConfig, load_config, save_config
from .gitlab_service import GitLabApiResult, GitLabService
from .models import ReviewDecision, ReviewFileItem, ScriptAvailability
from .repo_service import ReviewerRepoService
from .review_store import ReviewStore


class ReviewerApp:
    def __init__(self, root: tk.Tk, config: ReviewerConfig) -> None:
        self.root = root
        self.config = config

        self.service: ReviewerRepoService | None = None
        self.store: ReviewStore | None = None
        self.scripts = ScriptAvailability()

        self.current_commit = ""
        self.base_ref = config.default_base_ref
        self.selected_path: str | None = None
        self.validation_state: dict[str, tuple[bool, str]] = {}
        self.file_items: dict[str, ReviewFileItem] = {}
        self.session_log_path: Path | None = None
        self.main_tabs = None
        self.logs_tab = None
        self.gitlab_service: GitLabService | None = None
        self.gitlab_project_id: int | None = None
        self.gitlab_user_profile: dict[str, object] | None = None
        self.gitlab_access_level: int = 0
        self.gitlab_merge_requests: dict[int, dict[str, object]] = {}
        self.selected_mr_iid: int | None = None

        self.repo_path_var = tk.StringVar(value=config.default_repo_path)
        self.branch_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.base_ref_var = tk.StringVar(value="")
        self.script_var = tk.StringVar(value="")

        self.reviewer_var = tk.StringVar(value="")
        self.gitlab_user_var = tk.StringVar(value=config.gitlab_username or "oauth2")
        self.gitlab_token_var = tk.StringVar(value="")
        self.token_status_var = tk.StringVar(value="GitLab token: not set")
        self.gitlab_url_var = tk.StringVar(value=config.gitlab_base_url)
        self.gitlab_project_var = tk.StringVar(value=config.gitlab_project_path)
        self.gitlab_login_status_var = tk.StringVar(value="GitLab API: not connected")
        self.gitlab_identity_var = tk.StringVar(value="Identity: n/a")
        self.gitlab_role_var = tk.StringVar(value="Role: n/a")
        self.gitlab_mr_status_var = tk.StringVar(value="Merge requests: not loaded")
        self.gitlab_mr_detail_var = tk.StringVar(value="No merge request selected")
        self.gitlab_only_my_reviews_var = tk.BooleanVar(value=True)
        self.search_var = tk.StringVar(value="")
        self.ticket_var = tk.StringVar(value="")
        self.release_id_var = tk.StringVar(value="")
        self.publish_dest_var = tk.StringVar(value="")
        self.ignore_comments_var = tk.BooleanVar(value=config.ignore_comments_by_default)

        self.file_detail_var = tk.StringVar(value="No file selected")
        self.lock_var = tk.StringVar(value="Lock: n/a")
        self.validation_var = tk.StringVar(value="Validation: not run")
        self.warning_var = tk.StringVar(value="Warnings: none")
        self.decision_hint_var = tk.StringVar(value="")

        self.root.title("EDL Reviewer Sign-Off Tool")
        self.root.geometry("1360x820")
        self.root.minsize(1080, 640)
        self.root.report_callback_exception = self.on_unhandled_exception

        self._build_ui()
        self._bind_events()

        if self.repo_path_var.get().strip():
            self.open_repo()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=8)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(9, weight=1)

        ttk.Label(top, text="Repo Path:").grid(row=0, column=0, sticky="w")
        self.repo_entry = ttk.Entry(top, textvariable=self.repo_path_var)
        self.repo_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(top, text="Browse", command=self.browse_repo).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(top, text="Open", command=self.open_repo).grid(row=0, column=3, padx=(0, 4))
        ttk.Button(top, text="Fetch Latest", command=self.fetch_latest).grid(row=0, column=4, padx=(0, 10))

        ttk.Label(top, text="Reviewer:").grid(row=0, column=5, sticky="e")
        self.reviewer_entry = ttk.Entry(top, textvariable=self.reviewer_var, width=22)
        self.reviewer_entry.grid(row=0, column=6, sticky="w", padx=(6, 8))

        ttk.Button(top, text="Refresh", command=self.refresh_all).grid(row=0, column=7, padx=(0, 8))
        ttk.Label(top, text="Branch:").grid(row=0, column=8, sticky="e")
        ttk.Label(top, textvariable=self.branch_var).grid(row=0, column=9, sticky="w")

        ttk.Label(top, text="Git Status:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(top, textvariable=self.status_var).grid(row=1, column=1, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(top, text="Base Ref:").grid(row=1, column=5, sticky="e", pady=(6, 0))
        ttk.Label(top, textvariable=self.base_ref_var).grid(row=1, column=6, sticky="w", pady=(6, 0))
        ttk.Checkbutton(top, text="Ignore # comments", variable=self.ignore_comments_var).grid(
            row=1,
            column=7,
            columnspan=2,
            sticky="w",
            pady=(6, 0),
        )
        ttk.Label(top, textvariable=self.script_var).grid(row=1, column=9, sticky="e", pady=(6, 0))

        ttk.Label(top, text="GitLab User:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.gitlab_user_entry = ttk.Entry(top, textvariable=self.gitlab_user_var, width=22)
        self.gitlab_user_entry.grid(row=2, column=1, sticky="w", padx=(6, 6), pady=(6, 0))
        ttk.Label(top, text="GitLab Token:").grid(row=2, column=2, sticky="e", pady=(6, 0))
        self.gitlab_token_entry = ttk.Entry(top, textvariable=self.gitlab_token_var, width=34, show="*")
        self.gitlab_token_entry.grid(row=2, column=3, sticky="w", padx=(6, 6), pady=(6, 0))
        self.apply_token_button = ttk.Button(top, text="Use Token", command=self.apply_gitlab_auth)
        self.apply_token_button.grid(row=2, column=4, padx=(0, 8), pady=(6, 0))
        ttk.Label(top, textvariable=self.token_status_var).grid(
            row=2,
            column=5,
            columnspan=5,
            sticky="w",
            pady=(6, 0),
        )

        ttk.Label(top, text="GitLab URL:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.gitlab_url_entry = ttk.Entry(top, textvariable=self.gitlab_url_var)
        self.gitlab_url_entry.grid(row=3, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))
        ttk.Label(top, text="Project:").grid(row=3, column=2, sticky="e", pady=(6, 0))
        self.gitlab_project_entry = ttk.Entry(top, textvariable=self.gitlab_project_var)
        self.gitlab_project_entry.grid(row=3, column=3, sticky="ew", padx=(6, 6), pady=(6, 0))
        self.gitlab_connect_button = ttk.Button(top, text="Connect GitLab", command=self.connect_gitlab)
        self.gitlab_connect_button.grid(row=3, column=4, padx=(0, 8), pady=(6, 0))
        ttk.Label(top, textvariable=self.gitlab_login_status_var).grid(
            row=3,
            column=5,
            columnspan=5,
            sticky="w",
            pady=(6, 0),
        )

        self.main_tabs = ttk.Notebook(self.root)
        self.main_tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        review_tab = ttk.Frame(self.main_tabs)
        gitlab_tab = ttk.Frame(self.main_tabs)
        release_tab = ttk.Frame(self.main_tabs)
        self.logs_tab = ttk.Frame(self.main_tabs)
        self.main_tabs.add(review_tab, text="Review")
        self.main_tabs.add(gitlab_tab, text="GitLab")
        self.main_tabs.add(release_tab, text="Release")
        self.main_tabs.add(self.logs_tab, text="Logs")

        review_tab.columnconfigure(0, weight=1)
        review_tab.rowconfigure(0, weight=1)

        body = ttk.Frame(review_tab, padding=(0, 0, 0, 0))
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Changed Files Requiring Review", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        self.search_entry = ttk.Entry(left, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.file_tree = ttk.Treeview(left, columns=("status",), show="tree headings", selectmode="browse")
        self.file_tree.heading("#0", text="File")
        self.file_tree.heading("status", text="Status")
        self.file_tree.column("#0", width=240, anchor="w")
        self.file_tree.column("status", width=180, anchor="w")
        self.file_tree.grid(row=1, column=0, sticky="nsew")

        file_scroll = ttk.Scrollbar(left, orient="vertical", command=self.file_tree.yview)
        file_scroll.grid(row=1, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=file_scroll.set)

        right = ttk.LabelFrame(body, text="Review Details", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=3)
        right.rowconfigure(3, weight=2)
        right.rowconfigure(4, weight=1)

        info = ttk.Frame(right)
        info.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        info.columnconfigure(1, weight=1)
        info.columnconfigure(5, weight=1)

        ttk.Label(info, text="Selected File:").grid(row=0, column=0, sticky="w")
        ttk.Label(info, textvariable=self.file_detail_var).grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(info, text="Ticket/Change:").grid(row=0, column=2, sticky="e")
        self.ticket_entry = ttk.Entry(info, textvariable=self.ticket_var, width=24)
        self.ticket_entry.grid(row=0, column=3, sticky="w", padx=(6, 12))
        ttk.Label(info, text="Validation:").grid(row=0, column=4, sticky="e")
        ttk.Label(info, textvariable=self.validation_var).grid(row=0, column=5, sticky="w", padx=(6, 0))

        ttk.Label(info, textvariable=self.lock_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(info, textvariable=self.warning_var).grid(row=1, column=3, columnspan=3, sticky="w", pady=(4, 0))

        split = tk.PanedWindow(right, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        split.grid(row=2, column=0, sticky="nsew", pady=(0, 6))

        base_frame = ttk.LabelFrame(split, text="Baseline (Base Ref)", padding=4)
        base_frame.columnconfigure(0, weight=1)
        base_frame.rowconfigure(0, weight=1)
        self.base_text = ScrolledText(base_frame, wrap="none", state="disabled")
        self.base_text.grid(row=0, column=0, sticky="nsew")
        split.add(base_frame)

        prop_frame = ttk.LabelFrame(split, text="Proposed (Working Copy)", padding=4)
        prop_frame.columnconfigure(0, weight=1)
        prop_frame.rowconfigure(0, weight=1)
        self.proposed_text = ScrolledText(prop_frame, wrap="none", state="disabled")
        self.proposed_text.grid(row=0, column=0, sticky="nsew")
        split.add(prop_frame)

        decision = ttk.LabelFrame(right, text="Reviewer Decision", padding=8)
        decision.grid(row=3, column=0, sticky="nsew")
        decision.columnconfigure(0, weight=1)
        decision.rowconfigure(0, weight=1)

        self.notes_text = ScrolledText(decision, wrap="word", height=6)
        self.notes_text.grid(row=0, column=0, columnspan=6, sticky="nsew")
        self.validate_button = ttk.Button(decision, text="Re-run Validation", command=self.rerun_validation)
        self.validate_button.grid(row=1, column=0, pady=(6, 0), padx=(0, 4), sticky="w")
        self.diff_button = ttk.Button(decision, text="Refresh Diff", command=self.refresh_selected)
        self.diff_button.grid(row=1, column=1, pady=(6, 0), padx=(0, 4), sticky="w")
        self.approve_button = ttk.Button(decision, text="Approve", command=self.approve_selected)
        self.approve_button.grid(row=1, column=2, pady=(6, 0), padx=(0, 4), sticky="w")
        self.reject_button = ttk.Button(decision, text="Reject", command=self.reject_selected)
        self.reject_button.grid(row=1, column=3, pady=(6, 0), padx=(0, 4), sticky="w")
        self.promote_button = ttk.Button(decision, text="Promote To Approved", command=self.promote_selected)
        self.promote_button.grid(row=1, column=4, pady=(6, 0), padx=(0, 4), sticky="w")
        ttk.Label(decision, textvariable=self.decision_hint_var).grid(row=1, column=5, sticky="e", pady=(6, 0))

        self.diff_text = ScrolledText(right, wrap="none", height=9, state="disabled")
        self.diff_text.grid(row=4, column=0, sticky="nsew")

        gitlab_tab.columnconfigure(0, weight=2)
        gitlab_tab.columnconfigure(1, weight=3)
        gitlab_tab.rowconfigure(1, weight=1)

        gitlab_session = ttk.LabelFrame(gitlab_tab, text="GitLab Session", padding=8)
        gitlab_session.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        gitlab_session.columnconfigure(4, weight=1)

        ttk.Label(gitlab_session, textvariable=self.gitlab_identity_var).grid(row=0, column=0, sticky="w")
        ttk.Label(gitlab_session, textvariable=self.gitlab_role_var).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Checkbutton(
            gitlab_session,
            text="Only MRs assigned to me",
            variable=self.gitlab_only_my_reviews_var,
            command=self.refresh_gitlab_merge_requests,
        ).grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.refresh_gitlab_mrs_button = ttk.Button(
            gitlab_session,
            text="Load Merge Requests",
            command=self.refresh_gitlab_merge_requests,
        )
        self.refresh_gitlab_mrs_button.grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Label(gitlab_session, textvariable=self.gitlab_mr_status_var).grid(row=0, column=4, sticky="e")

        mr_left = ttk.LabelFrame(gitlab_tab, text="Open Merge Requests", padding=8)
        mr_left.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        mr_left.columnconfigure(0, weight=1)
        mr_left.rowconfigure(0, weight=1)

        self.gitlab_mr_tree = ttk.Treeview(
            mr_left,
            columns=("author", "target", "approved"),
            show="tree headings",
            selectmode="browse",
        )
        self.gitlab_mr_tree.heading("#0", text="IID / Title")
        self.gitlab_mr_tree.heading("author", text="Author")
        self.gitlab_mr_tree.heading("target", text="Target")
        self.gitlab_mr_tree.heading("approved", text="Approved")
        self.gitlab_mr_tree.column("#0", width=420, anchor="w")
        self.gitlab_mr_tree.column("author", width=140, anchor="w")
        self.gitlab_mr_tree.column("target", width=120, anchor="w")
        self.gitlab_mr_tree.column("approved", width=90, anchor="center")
        self.gitlab_mr_tree.grid(row=0, column=0, sticky="nsew")

        mr_scroll = ttk.Scrollbar(mr_left, orient="vertical", command=self.gitlab_mr_tree.yview)
        mr_scroll.grid(row=0, column=1, sticky="ns")
        self.gitlab_mr_tree.configure(yscrollcommand=mr_scroll.set)

        mr_right = ttk.LabelFrame(gitlab_tab, text="Selected Merge Request", padding=8)
        mr_right.grid(row=1, column=1, sticky="nsew")
        mr_right.columnconfigure(0, weight=1)
        mr_right.rowconfigure(2, weight=1)

        ttk.Label(mr_right, textvariable=self.gitlab_mr_detail_var, wraplength=700, justify="left").grid(
            row=0,
            column=0,
            sticky="ew",
        )

        buttons = ttk.Frame(mr_right)
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        buttons.columnconfigure(6, weight=1)

        self.gitlab_approve_button = ttk.Button(buttons, text="Approve MR", command=self.approve_selected_mr)
        self.gitlab_approve_button.grid(row=0, column=0, padx=(0, 4))
        self.gitlab_unapprove_button = ttk.Button(buttons, text="Remove Approval", command=self.unapprove_selected_mr)
        self.gitlab_unapprove_button.grid(row=0, column=1, padx=(0, 4))
        self.gitlab_open_button = ttk.Button(buttons, text="Open In Browser", command=self.open_selected_mr_in_browser)
        self.gitlab_open_button.grid(row=0, column=2, padx=(0, 4))
        ttk.Label(buttons, text="Comment / Request Changes:").grid(row=0, column=3, padx=(8, 4), sticky="e")
        self.gitlab_send_note_button = ttk.Button(buttons, text="Send Note", command=self.send_mr_note)
        self.gitlab_send_note_button.grid(row=0, column=4, padx=(0, 4))

        self.gitlab_note_text = ScrolledText(mr_right, wrap="word", height=10)
        self.gitlab_note_text.grid(row=2, column=0, sticky="nsew")

        release_tab.columnconfigure(0, weight=1)
        release_tab.rowconfigure(0, weight=1)

        release = ttk.LabelFrame(release_tab, text="Release Readiness (Guarded)", padding=8)
        release.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        release.columnconfigure(0, weight=2)
        release.columnconfigure(1, weight=1)
        release.rowconfigure(1, weight=1)

        ttk.Label(release, text="Approved / Ready Items").grid(row=0, column=0, sticky="w")
        self.approved_list = tk.Listbox(release, height=7)
        self.approved_list.grid(row=1, column=0, sticky="nsew", padx=(0, 8))

        rel_right = ttk.Frame(release)
        rel_right.grid(row=1, column=1, sticky="nsew")
        rel_right.columnconfigure(1, weight=1)

        ttk.Label(rel_right, text="Release ID:").grid(row=0, column=0, sticky="w")
        self.release_combo = ttk.Combobox(rel_right, textvariable=self.release_id_var)
        self.release_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 6))
        ttk.Label(rel_right, text="Publish Dest:").grid(row=1, column=0, sticky="w")
        ttk.Entry(rel_right, textvariable=self.publish_dest_var).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 6))

        self.build_button = ttk.Button(rel_right, text="Build Release", command=self.build_release)
        self.build_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.publish_dry_button = ttk.Button(rel_right, text="Publish Dry-Run", command=lambda: self.publish_release(True))
        self.publish_dry_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.publish_button = ttk.Button(rel_right, text="Publish (Guarded)", command=lambda: self.publish_release(False))
        self.publish_button.grid(row=4, column=0, columnspan=2, sticky="ew")

        self.logs_tab.columnconfigure(0, weight=1)
        self.logs_tab.rowconfigure(0, weight=1)

        logs = ttk.LabelFrame(self.logs_tab, text="Activity Log", padding=8)
        logs.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)

        tabs = ttk.Notebook(logs)
        tabs.grid(row=0, column=0, sticky="nsew")

        t1 = ttk.Frame(tabs)
        t1.columnconfigure(0, weight=1)
        t1.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(t1, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        tabs.add(t1, text="Activity")

        t2 = ttk.Frame(tabs)
        t2.columnconfigure(0, weight=1)
        t2.rowconfigure(0, weight=1)
        self.command_text = ScrolledText(t2, wrap="word", state="disabled")
        self.command_text.grid(row=0, column=0, sticky="nsew")
        tabs.add(t2, text="Command Details")

        log_actions = ttk.Frame(logs)
        log_actions.grid(row=1, column=0, sticky="e", pady=(6, 0))
        self.export_log_button = ttk.Button(log_actions, text="Export Log", command=self.export_log)
        self.export_log_button.grid(row=0, column=0)
        self.open_log_button = ttk.Button(log_actions, text="Open Log Folder", command=self.open_log_folder)
        self.open_log_button.grid(row=0, column=1, padx=(6, 0))

        self.update_action_states()

    def _bind_events(self) -> None:
        self.repo_entry.bind("<Return>", lambda _e: self.open_repo())
        self.search_var.trace_add("write", lambda *_: self.populate_tree())
        self.file_tree.bind("<<TreeviewSelect>>", self.on_select_file)
        self.reviewer_entry.bind("<KeyRelease>", lambda _e: self.update_action_states())
        self.ticket_entry.bind("<KeyRelease>", lambda _e: self.update_action_states())
        self.notes_text.bind("<KeyRelease>", lambda _e: self.update_action_states())
        self.gitlab_user_entry.bind("<Return>", lambda _e: self.apply_gitlab_auth())
        self.gitlab_token_entry.bind("<Return>", lambda _e: self.apply_gitlab_auth())
        self.gitlab_url_entry.bind("<Return>", lambda _e: self.connect_gitlab())
        self.gitlab_project_entry.bind("<Return>", lambda _e: self.connect_gitlab())
        self.gitlab_mr_tree.bind("<<TreeviewSelect>>", self.on_select_merge_request)

    def now(self) -> str:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, text: str) -> None:
        line = f"[{self.now()}] {text}"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.write_session_log(line)

    def write_session_log(self, line: str) -> None:
        if not self.session_log_path:
            return
        try:
            self.session_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.session_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            # Never crash the UI on logging failure.
            pass

    def init_session_log(self) -> None:
        if not self.service:
            return

        try:
            log_dir = self.service.repo_path / "logs" / "reviewer"
            log_dir.mkdir(parents=True, exist_ok=True)

            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            user = self.service.git_user().replace(" ", "_")
            host = socket.gethostname().replace(" ", "_")
            self.session_log_path = log_dir / f"reviewer-{stamp}-{user}-{host}.log"

            header = [
                f"# EDL Reviewer Session Log",
                f"# started_at_local={dt.datetime.now().isoformat()}",
                f"# started_at_utc={dt.datetime.now(dt.timezone.utc).isoformat()}",
                f"# repo_path={self.service.repo_path}",
                f"# hostname={host}",
                f"# user={user}",
                f"# python={platform.python_version()}",
                f"# platform={platform.platform()}",
            ]
            self.session_log_path.write_text("\n".join(header) + "\n", encoding="utf-8")
        except Exception as exc:
            self.session_log_path = None
            self.log(f"Failed to initialize session log: {exc}")

    def diagnostics_hint(self) -> str:
        if self.session_log_path:
            return f"Diagnostics log: {self.session_log_path}"
        return "Diagnostics log not initialized."

    def capture_runtime_snapshot(self, reason: str) -> None:
        if not self.service:
            return

        self.log(f"SNAPSHOT: {reason}")
        self.log(f"Repo: {self.service.repo_path}")
        self.log(f"Branch: {self.service.git_branch()}")
        self.log(f"Git status: {self.service.git_status_summary()}")
        self.log(f"Selected path: {self.selected_path or '(none)'}")
        self.log(f"Base ref: {self.base_ref}")
        self.log(
            f"GitLab connected={self.gitlab_service is not None and self.gitlab_project_id is not None} "
            f"project_id={self.gitlab_project_id or 0} "
            f"role={self.gitlab_role_label(self.gitlab_access_level)} "
            f"selected_mr={self.selected_mr_iid or 0}"
        )
        changed = self.service.changed_review_files(self.base_ref)
        if changed:
            preview = ", ".join(changed[:20])
            if len(changed) > 20:
                preview += ", ..."
            self.log(f"Review files ({len(changed)}): {preview}")
        else:
            self.log("Review files (0): (none)")

    def on_unhandled_exception(self, exc_type, exc_value, exc_traceback) -> None:
        if self.main_tabs is not None and self.logs_tab is not None:
            self.main_tabs.select(self.logs_tab)
        trace = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)).rstrip()
        self.log("UNHANDLED EXCEPTION:")
        self.log(trace)
        self.capture_runtime_snapshot("unhandled exception")
        messagebox.showerror(
            "Unexpected Error",
            "An unexpected error occurred.\n\n"
            f"{exc_value}\n\n"
            f"{self.diagnostics_hint()}",
        )

    def show_command(self, result) -> None:
        payload = []
        payload.append(f"COMMAND: {result.command_display}")
        payload.append(f"EXIT CODE: {result.returncode}")
        payload.append("")
        payload.append("STDOUT:")
        payload.append(result.stdout.rstrip() or "(empty)")
        payload.append("")
        payload.append("STDERR:")
        payload.append(result.stderr.rstrip() or "(empty)")

        self.command_text.configure(state="normal")
        self.command_text.delete("1.0", "end")
        self.command_text.insert("1.0", "\n".join(payload))
        self.command_text.configure(state="disabled")

    def log_result(self, result) -> None:
        self.log(f"COMMAND: {result.command_display}")
        if result.stdout.strip():
            self.log("STDOUT: " + result.stdout.strip().splitlines()[-1])
        if result.stderr.strip():
            self.log("STDERR: " + result.stderr.strip().splitlines()[-1])
        self.log(f"EXIT CODE: {result.returncode}")
        self.show_command(result)
        if not result.ok:
            if self.main_tabs is not None and self.logs_tab is not None:
                self.main_tabs.select(self.logs_tab)
            self.capture_runtime_snapshot("command failed")
            self.log(self.diagnostics_hint())

    def current_gitlab_token(self) -> str:
        token = self.gitlab_token_var.get().strip()
        if token:
            return token
        return os.environ.get("GITLAB_TOKEN", "").strip()

    def ensure_gitlab_service(self) -> GitLabService | None:
        base_url = self.gitlab_url_var.get().strip()
        project_ref = self.gitlab_project_var.get().strip()
        token = self.current_gitlab_token()

        if not base_url:
            messagebox.showwarning("GitLab", "GitLab URL is required.")
            return None
        if not project_ref:
            messagebox.showwarning("GitLab", "GitLab project path or project ID is required.")
            return None
        if not token:
            messagebox.showwarning("GitLab", "GitLab token is required.")
            return None

        self.gitlab_service = GitLabService(base_url=base_url, token=token, project_ref=project_ref)
        return self.gitlab_service

    def gitlab_role_label(self, access_level: int) -> str:
        mapping = {
            10: "Guest",
            20: "Reporter",
            30: "Developer",
            40: "Maintainer",
            50: "Owner",
        }
        return mapping.get(access_level, f"Unknown ({access_level})")

    def log_gitlab_api(self, action: str, result: GitLabApiResult) -> None:
        status = result.status_code if result.status_code else "n/a"
        outcome = "OK" if result.ok else "FAIL"
        self.log(f"GITLAB {action}: {outcome} (status={status})")
        if result.error:
            self.log(f"GITLAB {action} error: {result.error}")
        if not result.ok and self.main_tabs is not None and self.logs_tab is not None:
            self.main_tabs.select(self.logs_tab)

    def initialize_gitlab_from_remote(self) -> None:
        if not self.service:
            return

        remote = self.service.git_origin_url()
        if not remote:
            return

        derived_url, derived_project = GitLabService.derive_from_remote(remote)

        changed = False
        if not self.gitlab_url_var.get().strip() and derived_url:
            self.gitlab_url_var.set(derived_url)
            changed = True
        if not self.gitlab_project_var.get().strip() and derived_project:
            self.gitlab_project_var.set(derived_project)
            changed = True

        if changed:
            self.config.gitlab_base_url = self.gitlab_url_var.get().strip()
            self.config.gitlab_project_path = self.gitlab_project_var.get().strip()
            save_config(self.config)
            self.log(f"Derived GitLab target from origin remote: {self.gitlab_url_var.get()} / {self.gitlab_project_var.get()}")

    def connect_gitlab(self) -> None:
        if not self.service:
            messagebox.showwarning("GitLab", "Open a repository first.")
            return

        api = self.ensure_gitlab_service()
        if not api:
            return

        who = api.whoami()
        self.log_gitlab_api("whoami", who)
        if not who.ok or not isinstance(who.payload, dict):
            messagebox.showerror("GitLab Login", f"GitLab login failed.\n\n{who.error or 'Unknown error'}")
            self.gitlab_login_status_var.set("GitLab API: login failed")
            self.gitlab_identity_var.set("Identity: n/a")
            self.gitlab_role_var.set("Role: n/a")
            self.gitlab_project_id = None
            self.gitlab_user_profile = None
            self.gitlab_access_level = 0
            self.update_action_states()
            return

        project = api.get_project()
        self.log_gitlab_api("get_project", project)
        if not project.ok or not isinstance(project.payload, dict):
            messagebox.showerror("GitLab Project", f"Could not load project.\n\n{project.error or 'Unknown error'}")
            self.gitlab_login_status_var.set("GitLab API: project lookup failed")
            self.gitlab_project_id = None
            self.gitlab_access_level = 0
            self.update_action_states()
            return

        self.gitlab_user_profile = who.payload
        project_payload = project.payload
        self.gitlab_project_id = int(project_payload.get("id", 0))

        username = str(who.payload.get("username", "")).strip()
        name = str(who.payload.get("name", "")).strip()

        access_level = 0
        user_id = who.payload.get("id")
        if isinstance(user_id, int) and self.gitlab_project_id:
            member = api.get_member(user_id=user_id, project_id=self.gitlab_project_id)
            self.log_gitlab_api("get_member", member)
            if member.ok and isinstance(member.payload, dict):
                access_level = int(member.payload.get("access_level", 0))
        self.gitlab_access_level = access_level

        self.gitlab_identity_var.set(f"Identity: {name} ({username})")
        self.gitlab_role_var.set(f"Role: {self.gitlab_role_label(access_level)}")
        self.gitlab_login_status_var.set(
            f"GitLab API: connected to project {project_payload.get('path_with_namespace', self.gitlab_project_var.get())}"
        )

        self.config.gitlab_base_url = self.gitlab_url_var.get().strip()
        self.config.gitlab_project_path = self.gitlab_project_var.get().strip()
        save_config(self.config)

        self.log("GitLab connection established.")
        self.refresh_gitlab_merge_requests()
        self.update_action_states()

    def refresh_gitlab_merge_requests(self) -> None:
        if not self.gitlab_service or not self.gitlab_project_id:
            return

        reviewer_username = ""
        if self.gitlab_only_my_reviews_var.get() and self.gitlab_user_profile:
            reviewer_username = str(self.gitlab_user_profile.get("username", "")).strip()

        result = self.gitlab_service.list_merge_requests(
            project_id=self.gitlab_project_id,
            reviewer_username=reviewer_username,
        )
        self.log_gitlab_api("list_merge_requests", result)
        if not result.ok or not isinstance(result.payload, list):
            messagebox.showerror("GitLab MRs", f"Failed to load merge requests.\n\n{result.error or 'Unknown error'}")
            self.gitlab_mr_status_var.set("Merge requests: load failed")
            self.update_action_states()
            return

        self.gitlab_merge_requests.clear()
        self.selected_mr_iid = None
        self.gitlab_mr_detail_var.set("No merge request selected")
        self.gitlab_note_text.configure(state="normal")
        self.gitlab_note_text.delete("1.0", "end")

        for item in self.gitlab_mr_tree.get_children():
            self.gitlab_mr_tree.delete(item)

        for entry in result.payload:
            if not isinstance(entry, dict):
                continue
            iid = int(entry.get("iid", 0))
            if iid <= 0:
                continue

            title = str(entry.get("title", "")).strip()
            author = ""
            author_payload = entry.get("author")
            if isinstance(author_payload, dict):
                author = str(author_payload.get("username", "")).strip()
            target = str(entry.get("target_branch", "")).strip()
            approved_text = "yes" if bool(entry.get("approved_by")) else "no"
            self.gitlab_merge_requests[iid] = entry
            self.gitlab_mr_tree.insert(
                "",
                "end",
                iid=str(iid),
                text=f"!{iid} {title}",
                values=(author, target, approved_text),
            )

        count = len(self.gitlab_merge_requests)
        if reviewer_username:
            self.gitlab_mr_status_var.set(f"Merge requests loaded: {count} (filtered to reviewer {reviewer_username})")
        else:
            self.gitlab_mr_status_var.set(f"Merge requests loaded: {count}")

        self.update_action_states()

    def selected_mr_required(self) -> int | None:
        if self.selected_mr_iid is None:
            messagebox.showwarning("GitLab MR", "Select a merge request first.")
            return None
        return self.selected_mr_iid

    def on_select_merge_request(self, _event: object = None) -> None:
        selection = self.gitlab_mr_tree.selection()
        if not selection:
            self.selected_mr_iid = None
            self.gitlab_mr_detail_var.set("No merge request selected")
            self.update_action_states()
            return

        try:
            iid = int(selection[0])
        except ValueError:
            self.selected_mr_iid = None
            self.gitlab_mr_detail_var.set("No merge request selected")
            self.update_action_states()
            return

        self.selected_mr_iid = iid
        self.load_merge_request_details(iid)
        self.update_action_states()

    def load_merge_request_details(self, mr_iid: int) -> None:
        if not self.gitlab_service or not self.gitlab_project_id:
            return

        result = self.gitlab_service.get_merge_request(self.gitlab_project_id, mr_iid)
        self.log_gitlab_api("get_merge_request", result)
        if not result.ok or not isinstance(result.payload, dict):
            self.gitlab_mr_detail_var.set(f"!{mr_iid} (detail unavailable): {result.error or 'Unknown error'}")
            return

        payload = result.payload
        self.gitlab_merge_requests[mr_iid] = payload
        title = str(payload.get("title", ""))
        state = str(payload.get("state", ""))
        source = str(payload.get("source_branch", ""))
        target = str(payload.get("target_branch", ""))
        web_url = str(payload.get("web_url", ""))
        author = ""
        author_payload = payload.get("author")
        if isinstance(author_payload, dict):
            author = str(author_payload.get("username", ""))

        self.gitlab_mr_detail_var.set(
            f"!{mr_iid} [{state}] by {author}\n"
            f"{title}\n"
            f"{source} -> {target}\n"
            f"{web_url}"
        )

    def approve_selected_mr(self) -> None:
        if not self.gitlab_service or not self.gitlab_project_id:
            messagebox.showwarning("GitLab MR", "Connect to GitLab first.")
            return
        if self.gitlab_access_level < 30:
            messagebox.showwarning(
                "GitLab MR",
                "Current GitLab role is below Developer. Reviewer approval typically requires Developer or higher.",
            )
            return

        mr_iid = self.selected_mr_required()
        if mr_iid is None:
            return

        result = self.gitlab_service.approve_merge_request(self.gitlab_project_id, mr_iid)
        self.log_gitlab_api("approve_merge_request", result)
        if result.ok:
            messagebox.showinfo("GitLab MR", f"Merge request !{mr_iid} approved.")
            self.load_merge_request_details(mr_iid)
            self.refresh_gitlab_merge_requests()
        else:
            messagebox.showerror("GitLab MR", f"Approval failed.\n\n{result.error or 'Unknown error'}")

    def unapprove_selected_mr(self) -> None:
        if not self.gitlab_service or not self.gitlab_project_id:
            messagebox.showwarning("GitLab MR", "Connect to GitLab first.")
            return

        mr_iid = self.selected_mr_required()
        if mr_iid is None:
            return

        if not messagebox.askyesno("GitLab MR", f"Remove your approval from !{mr_iid}?"):
            return

        result = self.gitlab_service.unapprove_merge_request(self.gitlab_project_id, mr_iid)
        self.log_gitlab_api("unapprove_merge_request", result)
        if result.ok:
            messagebox.showinfo("GitLab MR", f"Approval removed from merge request !{mr_iid}.")
            self.load_merge_request_details(mr_iid)
            self.refresh_gitlab_merge_requests()
        else:
            messagebox.showerror("GitLab MR", f"Remove approval failed.\n\n{result.error or 'Unknown error'}")

    def send_mr_note(self) -> None:
        if not self.gitlab_service or not self.gitlab_project_id:
            messagebox.showwarning("GitLab MR", "Connect to GitLab first.")
            return

        mr_iid = self.selected_mr_required()
        if mr_iid is None:
            return

        note = self.gitlab_note_text.get("1.0", "end-1c").strip()
        if not note:
            messagebox.showwarning("GitLab MR", "Enter a note/comment first.")
            return

        result = self.gitlab_service.add_merge_request_note(self.gitlab_project_id, mr_iid, note)
        self.log_gitlab_api("add_merge_request_note", result)
        if result.ok:
            messagebox.showinfo("GitLab MR", "Note posted to merge request.")
            self.gitlab_note_text.configure(state="normal")
            self.gitlab_note_text.delete("1.0", "end")
        else:
            messagebox.showerror("GitLab MR", f"Failed to post note.\n\n{result.error or 'Unknown error'}")

    def open_selected_mr_in_browser(self) -> None:
        mr_iid = self.selected_mr_required()
        if mr_iid is None:
            return

        payload = self.gitlab_merge_requests.get(mr_iid, {})
        web_url = str(payload.get("web_url", "")).strip()
        if not web_url:
            messagebox.showwarning("GitLab MR", "Web URL not available for this merge request.")
            return

        try:
            webbrowser.open(web_url)
            self.log(f"Opened merge request URL: {web_url}")
        except Exception as exc:
            self.log(f"Failed to open MR URL: {exc}")
            messagebox.showerror("GitLab MR", f"Could not open browser:\n{exc}")

    def apply_gitlab_auth(self, log_notice: bool = True) -> None:
        if not self.service:
            return

        username = self.gitlab_user_var.get().strip() or "oauth2"
        token = self.gitlab_token_var.get().strip()
        self.service.set_gitlab_auth(username, token)
        self.gitlab_service = None
        self.gitlab_project_id = None
        self.gitlab_user_profile = None
        self.gitlab_access_level = 0
        self.gitlab_login_status_var.set("GitLab API: not connected")
        self.gitlab_identity_var.set("Identity: n/a")
        self.gitlab_role_var.set("Role: n/a")
        self.gitlab_mr_status_var.set("Merge requests: not loaded")
        self.selected_mr_iid = None
        self.gitlab_merge_requests.clear()
        self.gitlab_mr_detail_var.set("No merge request selected")
        if hasattr(self, "gitlab_mr_tree"):
            for item in self.gitlab_mr_tree.get_children():
                self.gitlab_mr_tree.delete(item)
        if hasattr(self, "gitlab_note_text"):
            self.gitlab_note_text.configure(state="normal")
            self.gitlab_note_text.delete("1.0", "end")

        self.config.gitlab_username = username
        save_config(self.config)

        if self.service.gitlab_token_configured():
            source = "session token" if token else "GITLAB_TOKEN environment variable"
            self.token_status_var.set(f"GitLab token: configured ({source})")
            if log_notice:
                self.log(f"GitLab auth ready for '{username}' using {source}.")
        else:
            self.token_status_var.set("GitLab token: missing (set token or GITLAB_TOKEN env var)")
            if log_notice:
                self.log("GitLab token is not configured for network git commands.")

        self.update_action_states()

    def can_run_network_git(self) -> bool:
        if not self.service:
            return False

        if not self.service.git_origin_uses_http():
            return True

        return self.service.gitlab_token_configured()

    def ensure_network_git_ready(self, action_name: str) -> bool:
        if self.can_run_network_git():
            return True

        if self.service and self.service.git_origin_uses_http():
            messagebox.showwarning(
                "GitLab Token Required",
                f"'{action_name}' requires a GitLab token for HTTPS remotes.\n\n"
                "Enter your token and click 'Use Token'.",
            )
        else:
            messagebox.showwarning("Git", f"'{action_name}' is not available right now.")
        return False

    def set_text(self, widget: ScrolledText, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def render_diff(self, content: str) -> None:
        self.diff_text.configure(state="normal")
        self.diff_text.delete("1.0", "end")
        self.diff_text.insert("1.0", content or "(No line differences)")

        self.diff_text.tag_configure("plus", foreground="#0f7b0f")
        self.diff_text.tag_configure("minus", foreground="#b00020")
        self.diff_text.tag_configure("hunk", foreground="#1f5f99")

        lines = self.diff_text.get("1.0", "end-1c").splitlines()
        for i, line in enumerate(lines, start=1):
            start = f"{i}.0"
            end = f"{i}.end"
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                self.diff_text.tag_add("plus", start, end)
            elif line.startswith("-"):
                self.diff_text.tag_add("minus", start, end)
            elif line.startswith("@@"):
                self.diff_text.tag_add("hunk", start, end)

        self.diff_text.configure(state="disabled")

    def browse_repo(self) -> None:
        selected = filedialog.askdirectory(
            title="Select EDL Repo",
            initialdir=self.repo_path_var.get().strip() or str(Path.cwd()),
        )
        if selected:
            self.repo_path_var.set(selected)
            self.open_repo()

    def open_repo(self) -> None:
        path_text = self.repo_path_var.get().strip()
        if not path_text:
            messagebox.showerror("Repo", "Please provide a repository path.")
            return

        repo_path = Path(path_text)
        if not repo_path.exists():
            messagebox.showerror("Repo", f"Path does not exist:\n{repo_path}")
            return

        service = ReviewerRepoService(repo_path)
        ok, detail = service.validate_structure()
        if not ok:
            messagebox.showerror("Repo", detail)
            self.log("Invalid repository structure: " + detail.replace("\n", " | "))
            return

        self.service = service
        self.store = ReviewStore(repo_path)
        self.scripts = service.detect_scripts()
        self.init_session_log()
        self.apply_gitlab_auth(log_notice=False)
        self.initialize_gitlab_from_remote()

        self.validation_state.clear()
        self.file_items.clear()
        self.selected_path = None
        self.gitlab_merge_requests.clear()
        self.selected_mr_iid = None
        for item in self.gitlab_mr_tree.get_children():
            self.gitlab_mr_tree.delete(item)
        self.gitlab_mr_detail_var.set("No merge request selected")
        self.gitlab_note_text.configure(state="normal")
        self.gitlab_note_text.delete("1.0", "end")

        self.config.default_repo_path = str(repo_path)
        save_config(self.config)

        self.clear_current_view()
        self.log(f"Opened repository: {repo_path}")
        self.log(self.diagnostics_hint())
        self.capture_runtime_snapshot("repo opened")
        self.refresh_all()

    def clear_current_view(self) -> None:
        self.file_detail_var.set("No file selected")
        self.lock_var.set("Lock: n/a")
        self.validation_var.set("Validation: not run")
        self.warning_var.set("Warnings: none")
        self.ticket_var.set("")
        self.notes_text.delete("1.0", "end")
        self.set_text(self.base_text, "")
        self.set_text(self.proposed_text, "")
        self.render_diff("")

    def fetch_latest(self) -> None:
        if not self.service:
            return
        if not self.service.git_available():
            messagebox.showerror("Fetch", "Git is not available for this repo path.")
            return
        if not self.ensure_network_git_ready("Fetch Latest"):
            return

        result = self.service.fetch_latest()
        self.log_result(result)
        if result.ok:
            messagebox.showinfo("Fetch", "Fetch completed.")
        else:
            messagebox.showerror("Fetch", f"Fetch failed.\n\n{self.diagnostics_hint()}")

        self.refresh_all()

    def refresh_all(self) -> None:
        if not self.service:
            self.update_action_states()
            return

        self.branch_var.set(self.service.git_branch())
        self.status_var.set(self.service.git_status_summary())
        self.current_commit = self.service.current_commit()

        self.base_ref = self.service.resolve_base_ref(self.config.default_base_ref)
        self.base_ref_var.set(self.base_ref)

        if not self.reviewer_var.get().strip():
            self.reviewer_var.set(self.service.git_user())

        self.scripts = self.service.detect_scripts()
        if self.scripts.missing:
            self.script_var.set("Missing scripts: " + ", ".join(self.scripts.missing))
        else:
            self.script_var.set("All review scripts detected.")

        if self.service.gitlab_token_configured():
            source = "session token" if self.gitlab_token_var.get().strip() else "GITLAB_TOKEN environment variable"
            self.token_status_var.set(f"GitLab token: configured ({source})")
        else:
            self.token_status_var.set("GitLab token: missing (set token or GITLAB_TOKEN env var)")

        self.load_review_items()
        self.refresh_release_ids()
        self.update_action_states()

    def load_review_items(self) -> None:
        if not self.service or not self.store:
            return

        previous = self.selected_path
        self.file_items.clear()

        changed = self.service.changed_review_files(self.base_ref)
        for rel_path in changed:
            validation = self.validation_state.get(rel_path)
            val_ok = validation[0] if validation else None
            val_summary = validation[1] if validation else "Validation not run in this session."
            decision = self.store.load(rel_path)
            lock = self.service.lock_for_rel_path(rel_path)

            status, ready = self._status_for(rel_path, decision, val_ok)
            self.file_items[rel_path] = ReviewFileItem(
                rel_path=rel_path,
                name=Path(rel_path).name,
                status=status,
                lock=lock,
                validation_ok=val_ok,
                validation_summary=val_summary,
                decision=decision,
                ready_for_release=ready,
            )

        self.populate_tree()
        self.refresh_approved_items()

        if previous and previous in self.file_items:
            self.file_tree.selection_set(previous)
            self.file_tree.focus(previous)
            self.selected_path = previous
            self.load_selected_file()
        elif self.file_tree.get_children():
            first = self.file_tree.get_children()[0]
            self.file_tree.selection_set(first)
            self.file_tree.focus(first)
            self.selected_path = first
            self.load_selected_file()
        else:
            self.selected_path = None
            self.clear_current_view()

    def _status_for(self, rel_path: str, decision: ReviewDecision | None, val_ok: bool | None) -> tuple[str, bool]:
        if val_ok is False:
            return "validation failed", False

        if decision and decision.latest_commit_hash == self.current_commit:
            if decision.decision == "rejected":
                return "rejected", False
            if decision.decision == "approved":
                ready = self.service.approved_matches_working(rel_path) if self.service else False
                if ready:
                    return "ready for release", True
                return "approved", False

        return "pending review", False

    def populate_tree(self) -> None:
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        search = self.search_var.get().strip().lower()
        for rel_path, item in sorted(self.file_items.items(), key=lambda kv: kv[1].name.lower()):
            if search and search not in item.name.lower() and search not in rel_path.lower():
                continue
            self.file_tree.insert("", "end", iid=rel_path, text=item.name, values=(item.status,))

    def on_select_file(self, _event: object = None) -> None:
        selected = self.file_tree.selection()
        if not selected:
            return
        self.selected_path = selected[0]
        self.load_selected_file()

    def load_selected_file(self) -> None:
        if not self.service or not self.selected_path:
            return

        item = self.file_items.get(self.selected_path)
        if not item:
            return

        baseline = self.service.read_file_from_ref(self.base_ref, self.selected_path)
        proposed = self.service.read_working_file(self.selected_path)
        diff = self.service.unified_diff(baseline, proposed, self.selected_path)

        self.set_text(self.base_text, baseline)
        self.set_text(self.proposed_text, proposed)
        self.render_diff(diff)

        self.file_detail_var.set(f"{self.selected_path} ({item.status})")

        if item.lock:
            self.lock_var.set(
                "Lock: "
                f"{item.lock.locked_by} on {item.lock.machine} "
                f"ticket={item.lock.ticket} at {item.lock.timestamp}"
            )
        else:
            self.lock_var.set("Lock: none")

        if item.validation_ok is True:
            self.validation_var.set(f"Validation: PASS - {item.validation_summary}")
        elif item.validation_ok is False:
            self.validation_var.set(f"Validation: FAIL - {item.validation_summary}")
        else:
            self.validation_var.set(f"Validation: UNKNOWN - {item.validation_summary}")

        duplicates = self.service.duplicate_lines(proposed)
        if duplicates:
            self.warning_var.set(f"Warnings: duplicate lines detected ({len(duplicates)})")
        else:
            self.warning_var.set("Warnings: none")

        self.notes_text.delete("1.0", "end")
        if item.decision:
            self.ticket_var.set(item.decision.ticket)
            self.notes_text.insert("1.0", item.decision.notes)

        self.update_action_states()

    def refresh_selected(self) -> None:
        path = self.selected_required()
        if not path:
            return

        self.load_review_items()
        if path in self.file_items:
            self.file_tree.selection_set(path)
            self.file_tree.focus(path)
            self.selected_path = path
            self.load_selected_file()

    def selected_required(self) -> str | None:
        if not self.selected_path:
            messagebox.showwarning("Selection", "Select a changed file first.")
            return None
        return self.selected_path

    def reviewer_required(self) -> str | None:
        reviewer = self.reviewer_var.get().strip()
        if not reviewer:
            messagebox.showwarning("Reviewer", "Reviewer name is required.")
            return None
        return reviewer

    def ticket_required(self) -> str | None:
        ticket = self.ticket_var.get().strip()
        if not ticket:
            messagebox.showwarning("Ticket", "Ticket/change number is required.")
            return None
        return ticket

    def notes_value(self) -> str:
        return self.notes_text.get("1.0", "end-1c").strip()

    def rerun_validation(self) -> bool:
        if not self.service:
            return False
        if not self.scripts.validate:
            messagebox.showerror("Validation", "validate.ps1 is missing in scripts/.")
            return False

        rel_path = self.selected_required()
        if not rel_path:
            return False

        result = self.service.run_validation(rel_path, ignore_comments=self.ignore_comments_var.get())
        self.log_result(result)

        summary = self.service.summarize_validation(result)
        self.validation_state[rel_path] = (result.ok, summary)

        if result.ok:
            messagebox.showinfo("Validation", "Validation passed.")
        else:
            messagebox.showerror("Validation", f"Validation failed.\n\n{self.diagnostics_hint()}")

        self.load_review_items()
        return result.ok

    def approve_selected(self) -> None:
        if not self.service or not self.store:
            return

        rel_path = self.selected_required()
        if not rel_path:
            return

        reviewer = self.reviewer_required()
        if not reviewer:
            return

        ticket = self.ticket_required()
        if not ticket:
            return

        validation = self.validation_state.get(rel_path)
        if not validation or validation[0] is not True:
            messagebox.showwarning(
                "Approve",
                "Approve requires passing validation in this review session. Run Re-run Validation first.",
            )
            return

        notes = self.notes_value()

        if not messagebox.askyesno("Confirm Approval", f"Approve {rel_path}?\n\nTicket: {ticket}\nReviewer: {reviewer}"):
            return

        record = ReviewDecision(
            filename=rel_path,
            ticket=ticket,
            decision="approved",
            reviewer=reviewer,
            timestamp=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            notes=notes,
            source_branch=self.branch_var.get(),
            latest_commit_hash=self.current_commit,
            base_ref=self.base_ref,
            validation_ok=True,
        )

        path = self.store.save(record)
        self.log(f"Approval recorded: {path}")
        messagebox.showinfo("Approve", f"Approval recorded.\n{path}")
        self.load_review_items()

    def reject_selected(self) -> None:
        if not self.service or not self.store:
            return

        rel_path = self.selected_required()
        if not rel_path:
            return

        reviewer = self.reviewer_required()
        if not reviewer:
            return

        ticket = self.ticket_required()
        if not ticket:
            return

        notes = self.notes_value()
        if not notes:
            messagebox.showwarning("Reject", "Reject requires reviewer notes.")
            return

        validation = self.validation_state.get(rel_path)
        validation_ok = bool(validation and validation[0])

        if not messagebox.askyesno("Confirm Rejection", f"Reject {rel_path}?\n\nTicket: {ticket}\nReviewer: {reviewer}"):
            return

        record = ReviewDecision(
            filename=rel_path,
            ticket=ticket,
            decision="rejected",
            reviewer=reviewer,
            timestamp=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            notes=notes,
            source_branch=self.branch_var.get(),
            latest_commit_hash=self.current_commit,
            base_ref=self.base_ref,
            validation_ok=validation_ok,
        )

        path = self.store.save(record)
        self.log(f"Rejection recorded: {path}")
        messagebox.showinfo("Reject", f"Rejection recorded.\n{path}")
        self.load_review_items()

    def promote_selected(self) -> None:
        if not self.service:
            return

        rel_path = self.selected_required()
        if not rel_path:
            return

        item = self.file_items.get(rel_path)
        if not item or item.status not in {"approved", "ready for release"}:
            messagebox.showwarning("Promote", "Promote is only allowed after current-commit approval.")
            return

        if not messagebox.askyesno(
            "Confirm Promote",
            f"Copy {Path(rel_path).name} from edl/working to edl/approved?",
        ):
            return

        try:
            self.service.promote_to_approved(rel_path)
            self.log(f"Promoted {rel_path} to edl/approved/{Path(rel_path).name}")
            messagebox.showinfo("Promote", "Promotion completed.")
            self.load_review_items()
        except Exception as exc:
            self.log(f"Promotion failed: {exc}")
            messagebox.showerror("Promote", f"Promotion failed:\n{exc}\n\n{self.diagnostics_hint()}")

    def refresh_approved_items(self) -> None:
        self.approved_list.delete(0, "end")
        for _, item in sorted(self.file_items.items(), key=lambda kv: kv[1].name.lower()):
            if item.status in {"approved", "ready for release"}:
                self.approved_list.insert("end", f"{item.name} [{item.status}]")

    def refresh_release_ids(self) -> None:
        if not self.service:
            return
        ids = self.service.release_ids()
        self.release_combo["values"] = ids
        if not self.release_id_var.get().strip() and ids:
            self.release_id_var.set(ids[-1])

    def build_release(self) -> None:
        if not self.service:
            return
        if not self.scripts.build_release:
            messagebox.showerror("Build Release", "build-release.ps1 is missing in scripts/.")
            return

        release_id = self.release_id_var.get().strip() or None
        prompt = "Build release from edl/approved content?"
        if release_id:
            prompt += f"\n\nRelease ID: {release_id}"

        if not messagebox.askyesno("Confirm Build Release", prompt):
            return

        result = self.service.build_release(release_id)
        self.log_result(result)
        if result.ok:
            for line in result.stdout.splitlines():
                if line.strip().lower().startswith("release id"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        self.release_id_var.set(parts[1].strip())
            messagebox.showinfo("Build Release", "Release build succeeded.")
        else:
            messagebox.showerror("Build Release", f"Release build failed.\n\n{self.diagnostics_hint()}")

        self.refresh_all()

    def publish_release(self, dry_run: bool) -> None:
        if not self.service:
            return
        if not self.scripts.publish_release:
            messagebox.showerror("Publish", "publish-release.ps1 is missing in scripts/.")
            return

        release_id = self.release_id_var.get().strip()
        if not release_id:
            messagebox.showwarning("Publish", "Release ID is required.")
            return

        if dry_run:
            if not messagebox.askyesno("Confirm Dry-Run", f"Run publish dry-run for {release_id}?"):
                return
        else:
            if not messagebox.askyesno("Confirm Publish", f"Publish release {release_id}? This is a guarded action."):
                return
            phrase = simpledialog.askstring(
                "Publish Confirmation",
                f"Type EXACTLY: PUBLISH {release_id}",
                parent=self.root,
            )
            if phrase != f"PUBLISH {release_id}":
                messagebox.showwarning("Publish", "Confirmation text mismatch. Publish cancelled.")
                return

        result = self.service.publish_release(
            release_id=release_id,
            destination=self.publish_dest_var.get().strip(),
            dry_run=dry_run,
        )
        self.log_result(result)
        if result.ok:
            messagebox.showinfo("Publish", "Publish command completed.")
        else:
            messagebox.showerror("Publish", f"Publish command failed.\n\n{self.diagnostics_hint()}")

    def export_log(self) -> None:
        content = self.log_text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo("Export Log", "No log content to export.")
            return

        target = filedialog.asksaveasfilename(
            title="Export Activity Log",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not target:
            return

        Path(target).write_text(content, encoding="utf-8")
        self.log(f"Exported activity log to {target}")

    def open_log_folder(self) -> None:
        if self.session_log_path:
            folder = self.session_log_path.parent
        elif self.service:
            folder = self.service.repo_path / "logs" / "reviewer"
            folder.mkdir(parents=True, exist_ok=True)
        else:
            messagebox.showinfo("Open Log Folder", "Open a repo first.")
            return

        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
            self.log(f"Opened log folder: {folder}")
        except Exception as exc:
            self.log(f"Failed to open log folder: {exc}")
            messagebox.showerror("Open Log Folder", f"Could not open log folder:\n{exc}")

    def _approve_hint(self) -> str:
        if not self.selected_path:
            return "Select a file to review."
        if not self.reviewer_var.get().strip():
            return "Reviewer name required."
        if not self.ticket_var.get().strip():
            return "Ticket/change number required."
        validation = self.validation_state.get(self.selected_path)
        if not validation or validation[0] is not True:
            return "Approve disabled until validation passes."
        return "Ready for approval."

    def update_action_states(self) -> None:
        has_service = self.service is not None
        has_file = self.selected_path is not None
        self.apply_token_button.configure(state="normal" if has_service else "disabled")
        self.gitlab_connect_button.configure(state="normal" if has_service else "disabled")
        self.open_log_button.configure(state="normal" if has_service else "disabled")
        self.export_log_button.configure(state="normal")

        self.validate_button.configure(state="normal" if (has_service and has_file and self.scripts.validate) else "disabled")
        self.diff_button.configure(state="normal" if (has_service and has_file) else "disabled")

        hint = self._approve_hint()
        approve_on = hint == "Ready for approval."
        self.approve_button.configure(state="normal" if approve_on else "disabled")

        reject_on = (
            has_service and has_file and bool(self.reviewer_var.get().strip()) and
            bool(self.ticket_var.get().strip()) and bool(self.notes_value())
        )
        self.reject_button.configure(state="normal" if reject_on else "disabled")

        promote_on = False
        if has_service and has_file and self.selected_path in self.file_items:
            promote_on = self.file_items[self.selected_path].status in {"approved", "ready for release"}
        self.promote_button.configure(state="normal" if promote_on else "disabled")

        self.decision_hint_var.set("Approve enabled" if approve_on else hint)

        build_on = has_service and self.scripts.build_release
        publish_on = has_service and self.scripts.publish_release
        self.build_button.configure(state="normal" if build_on else "disabled")
        self.publish_button.configure(state="normal" if publish_on else "disabled")
        self.publish_dry_button.configure(state="normal" if publish_on else "disabled")

        gitlab_connected = self.gitlab_service is not None and self.gitlab_project_id is not None
        self.refresh_gitlab_mrs_button.configure(state="normal" if gitlab_connected else "disabled")

        has_selected_mr = self.selected_mr_iid is not None
        state_mr = "normal" if (gitlab_connected and has_selected_mr) else "disabled"
        approval_state = "normal" if (state_mr == "normal" and self.gitlab_access_level >= 30) else "disabled"
        self.gitlab_approve_button.configure(state=approval_state)
        self.gitlab_unapprove_button.configure(state=approval_state)
        self.gitlab_open_button.configure(state=state_mr)
        self.gitlab_send_note_button.configure(state=state_mr)
        self.gitlab_note_text.configure(state="normal" if state_mr == "normal" else "disabled")

    def on_close(self) -> None:
        self.config.default_repo_path = self.repo_path_var.get().strip()
        self.config.default_base_ref = self.base_ref
        self.config.ignore_comments_by_default = self.ignore_comments_var.get()
        self.config.gitlab_username = self.gitlab_user_var.get().strip() or "oauth2"
        self.config.gitlab_base_url = self.gitlab_url_var.get().strip()
        self.config.gitlab_project_path = self.gitlab_project_var.get().strip()
        save_config(self.config)
        self.root.destroy()


def create_root(theme: str) -> tk.Tk:
    if HAS_TTKBOOTSTRAP and ttkbootstrap is not None:
        return ttkbootstrap.Window(themename=theme)
    return tk.Tk()


def run() -> None:
    config = load_config()
    root = create_root(config.theme)
    app = ReviewerApp(root, config)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    run()
