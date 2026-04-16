"""Reviewer desktop UI for EDL sign-off workflow."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import tkinter as tk
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

        self.repo_path_var = tk.StringVar(value=config.default_repo_path)
        self.branch_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.base_ref_var = tk.StringVar(value="")
        self.script_var = tk.StringVar(value="")

        self.reviewer_var = tk.StringVar(value="")
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
        self.root.geometry("1600x950")
        self.root.minsize(1250, 760)

        self._build_ui()
        self._bind_events()

        if self.repo_path_var.get().strip():
            self.open_repo()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=4)
        self.root.rowconfigure(2, weight=2)
        self.root.rowconfigure(3, weight=2)

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

        body = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        body.grid(row=1, column=0, sticky="nsew")
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

        release = ttk.LabelFrame(self.root, text="Release Readiness (Guarded)", padding=8)
        release.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
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

        logs = ttk.LabelFrame(self.root, text="Activity Log", padding=8)
        logs.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
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

        self.update_action_states()

    def _bind_events(self) -> None:
        self.repo_entry.bind("<Return>", lambda _e: self.open_repo())
        self.search_var.trace_add("write", lambda *_: self.populate_tree())
        self.file_tree.bind("<<TreeviewSelect>>", self.on_select_file)
        self.reviewer_entry.bind("<KeyRelease>", lambda _e: self.update_action_states())
        self.ticket_entry.bind("<KeyRelease>", lambda _e: self.update_action_states())
        self.notes_text.bind("<KeyRelease>", lambda _e: self.update_action_states())

    def now(self) -> str:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{self.now()}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

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

        self.validation_state.clear()
        self.file_items.clear()
        self.selected_path = None

        self.config.default_repo_path = str(repo_path)
        save_config(self.config)

        self.clear_current_view()
        self.log(f"Opened repository: {repo_path}")
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

        result = self.service.fetch_latest()
        self.log_result(result)
        if result.ok:
            messagebox.showinfo("Fetch", "Fetch completed.")
        else:
            messagebox.showerror("Fetch", "Fetch failed. See command details.")

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
            messagebox.showerror("Validation", "Validation failed. See command details.")

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
            messagebox.showerror("Promote", f"Promotion failed:\n{exc}")

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
            messagebox.showerror("Build Release", "Release build failed. See command details.")

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
            messagebox.showerror("Publish", "Publish command failed. See command details.")

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

    def on_close(self) -> None:
        self.config.default_repo_path = self.repo_path_var.get().strip()
        self.config.default_base_ref = self.base_ref
        self.config.ignore_comments_by_default = self.ignore_comments_var.get()
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
