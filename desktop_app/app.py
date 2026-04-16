"""Tkinter desktop app for local EDL workflow operations."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

try:
    import ttkbootstrap as ttkbootstrap  # type: ignore

    HAS_TTKBOOTSTRAP = True
    ttk = ttkbootstrap
except Exception:
    from tkinter import ttk  # type: ignore

    HAS_TTKBOOTSTRAP = False
    ttkbootstrap = None

from .config import AppConfig, load_config, save_config
from .models import CommandResult, FileItem, ScriptAvailability
from .repo_service import RepoService


class EDLDesktopApp:
    def __init__(self, root: tk.Tk, config: AppConfig) -> None:
        self.root = root
        self.config = config
        self.service: RepoService | None = None
        self.script_availability = ScriptAvailability()

        self.current_file: str | None = None
        self.loaded_text = ""
        self.is_dirty = False
        self.validation_failures: set[str] = set()

        self.repo_path_var = tk.StringVar(value=config.default_repo_path)
        self.branch_var = tk.StringVar(value="")
        self.user_var = tk.StringVar(value="")
        self.search_var = tk.StringVar(value="")
        self.ticket_var = tk.StringVar(value="")
        self.file_status_var = tk.StringVar(value="No file selected")
        self.lock_detail_var = tk.StringVar(value="")
        self.duplicate_var = tk.StringVar(value="Duplicate lines: 0")
        self.script_status_var = tk.StringVar(value="")
        self.new_branch_var = tk.StringVar(value="")
        self.commit_message_var = tk.StringVar(value="")
        self.release_id_var = tk.StringVar(value="")
        self.publish_dest_var = tk.StringVar(value="")
        self.ignore_comments_var = tk.BooleanVar(value=config.ignore_comments_by_default)

        self.file_index: dict[str, FileItem] = {}

        self.root.title("EDL Repo Operator Tool")
        self.root.geometry("1400x900")
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.build_layout()
        self.bind_events()

        if self.repo_path_var.get().strip():
            self.open_repo()

    def build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=4)
        self.root.rowconfigure(2, weight=2)
        self.root.rowconfigure(3, weight=2)

        top = ttk.Frame(self.root, padding=8)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(8, weight=1)

        ttk.Label(top, text="Repo Path:").grid(row=0, column=0, sticky="w")
        self.repo_entry = ttk.Entry(top, textvariable=self.repo_path_var)
        self.repo_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))

        self.browse_button = ttk.Button(top, text="Browse", command=self.browse_repo)
        self.browse_button.grid(row=0, column=2, padx=(0, 6))

        self.open_button = ttk.Button(top, text="Open Repo", command=self.open_repo)
        self.open_button.grid(row=0, column=3, padx=(0, 10))

        ttk.Label(top, text="Branch:").grid(row=0, column=4, sticky="e")
        ttk.Label(top, textvariable=self.branch_var).grid(row=0, column=5, sticky="w", padx=(4, 12))

        ttk.Label(top, text="User:").grid(row=0, column=6, sticky="e")
        ttk.Label(top, textvariable=self.user_var).grid(row=0, column=7, sticky="w", padx=(4, 12))

        self.refresh_button = ttk.Button(top, text="Refresh", command=self.refresh_all)
        self.refresh_button.grid(row=0, column=8, sticky="e", padx=(8, 0))

        ttk.Label(top, textvariable=self.script_status_var).grid(row=1, column=0, columnspan=9, sticky="w", pady=(6, 0))

        middle = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        middle.grid(row=1, column=0, sticky="nsew")
        middle.columnconfigure(0, weight=1)
        middle.columnconfigure(1, weight=3)
        middle.rowconfigure(0, weight=1)

        self.left_frame = ttk.LabelFrame(middle, text="EDL Files", padding=8)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.left_frame.columnconfigure(0, weight=1)
        self.left_frame.rowconfigure(1, weight=1)

        self.search_entry = ttk.Entry(self.left_frame, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.file_tree = ttk.Treeview(self.left_frame, columns=("status",), show="tree headings", selectmode="browse")
        self.file_tree.heading("#0", text="File")
        self.file_tree.heading("status", text="Status")
        self.file_tree.column("#0", width=220, anchor="w")
        self.file_tree.column("status", width=220, anchor="w")
        self.file_tree.grid(row=1, column=0, sticky="nsew")

        tree_scroll = ttk.Scrollbar(self.left_frame, orient="vertical", command=self.file_tree.yview)
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=tree_scroll.set)

        self.main_frame = ttk.LabelFrame(middle, text="Working File", padding=8)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(3, weight=1)

        ttk.Label(self.main_frame, textvariable=self.file_status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(self.main_frame, textvariable=self.lock_detail_var).grid(row=1, column=0, sticky="w", pady=(2, 6))

        controls = ttk.Frame(self.main_frame)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(8, weight=1)

        ttk.Label(controls, text="Ticket/Change:").grid(row=0, column=0, sticky="w")
        self.ticket_entry = ttk.Entry(controls, textvariable=self.ticket_var, width=20)
        self.ticket_entry.grid(row=0, column=1, sticky="w", padx=(4, 8))

        self.checkout_button = ttk.Button(controls, text="Checkout", command=self.checkout_selected)
        self.checkout_button.grid(row=0, column=2, padx=2)

        self.validate_button = ttk.Button(controls, text="Validate", command=self.validate_selected)
        self.validate_button.grid(row=0, column=3, padx=2)

        self.checkin_button = ttk.Button(controls, text="Checkin", command=self.checkin_selected)
        self.checkin_button.grid(row=0, column=4, padx=2)

        self.save_button = ttk.Button(controls, text="Save", command=self.save_current_file)
        self.save_button.grid(row=0, column=5, padx=2)

        self.refresh_file_button = ttk.Button(controls, text="Refresh File", command=self.reload_current_file)
        self.refresh_file_button.grid(row=0, column=6, padx=2)

        ttk.Checkbutton(
            controls,
            text="Ignore # comments",
            variable=self.ignore_comments_var,
        ).grid(row=0, column=7, padx=(8, 0))

        ttk.Label(controls, textvariable=self.duplicate_var).grid(row=0, column=8, sticky="e")

        self.editor_text = ScrolledText(self.main_frame, wrap="none", undo=True)
        self.editor_text.grid(row=3, column=0, sticky="nsew")
        self.editor_text.configure(state="disabled")

        log_frame = ttk.LabelFrame(self.root, text="Activity Log", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = ScrolledText(log_frame, wrap="word", state="disabled", height=10)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_actions = ttk.Frame(log_frame)
        log_actions.grid(row=1, column=0, sticky="e", pady=(6, 0))
        ttk.Button(log_actions, text="Export Log", command=self.export_log).grid(row=0, column=0)

        bottom = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        bottom.grid(row=3, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)

        self.git_frame = ttk.LabelFrame(bottom, text="Git Actions", padding=8)
        self.git_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.git_frame.columnconfigure(0, weight=1)
        self.git_frame.columnconfigure(1, weight=1)
        self.git_frame.rowconfigure(2, weight=1)

        branch_row = ttk.Frame(self.git_frame)
        branch_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        branch_row.columnconfigure(1, weight=1)

        ttk.Label(branch_row, text="New Branch:").grid(row=0, column=0, sticky="w")
        ttk.Entry(branch_row, textvariable=self.new_branch_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.create_branch_button = ttk.Button(branch_row, text="Create Branch", command=self.create_branch)
        self.create_branch_button.grid(row=0, column=2)

        commit_row = ttk.Frame(self.git_frame)
        commit_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        commit_row.columnconfigure(1, weight=1)

        ttk.Label(commit_row, text="Commit Message:").grid(row=0, column=0, sticky="w")
        ttk.Entry(commit_row, textvariable=self.commit_message_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.commit_button = ttk.Button(commit_row, text="Commit", command=self.commit_changes)
        self.commit_button.grid(row=0, column=2, padx=(0, 4))
        self.push_button = ttk.Button(commit_row, text="Push", command=self.push_branch)
        self.push_button.grid(row=0, column=3)

        ttk.Label(self.git_frame, text="Changed Files:").grid(row=2, column=0, sticky="nw")
        self.changed_listbox = tk.Listbox(self.git_frame, height=6)
        self.changed_listbox.grid(row=2, column=0, columnspan=2, sticky="nsew")

        self.release_frame = ttk.LabelFrame(bottom, text="Release Actions (Guarded)", padding=8)
        self.release_frame.grid(row=0, column=1, sticky="nsew")
        self.release_frame.columnconfigure(1, weight=1)

        ttk.Label(self.release_frame, text="Use only after approvals.").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )

        ttk.Label(self.release_frame, text="Release ID:").grid(row=1, column=0, sticky="w")
        ttk.Entry(self.release_frame, textvariable=self.release_id_var).grid(row=1, column=1, sticky="ew", padx=(6, 6))
        self.build_release_button = ttk.Button(self.release_frame, text="Build Release", command=self.build_release)
        self.build_release_button.grid(row=1, column=2)

        ttk.Label(self.release_frame, text="Publish Dest:").grid(row=2, column=0, sticky="w")
        ttk.Entry(self.release_frame, textvariable=self.publish_dest_var).grid(row=2, column=1, sticky="ew", padx=(6, 6))
        actions = ttk.Frame(self.release_frame)
        actions.grid(row=2, column=2, sticky="e")
        self.publish_dry_button = ttk.Button(actions, text="Dry Run", command=lambda: self.publish_release(dry_run=True))
        self.publish_dry_button.grid(row=0, column=0, padx=(0, 4))
        self.publish_button = ttk.Button(actions, text="Publish", command=lambda: self.publish_release(dry_run=False))
        self.publish_button.grid(row=0, column=1)

        self.update_action_states()

    def bind_events(self) -> None:
        self.search_var.trace_add("write", lambda *_: self.populate_file_list())
        self.file_tree.bind("<<TreeviewSelect>>", self.on_file_selected)
        self.editor_text.bind("<<Modified>>", self.on_editor_modified)
        self.editor_text.bind("<Control-s>", lambda e: self.save_current_file() or "break")
        self.repo_entry.bind("<Return>", lambda e: self.open_repo())

    def timestamp(self) -> str:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{self.timestamp()}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def log_command_result(self, result: CommandResult) -> None:
        self.log(f"COMMAND: {' '.join(result.command)}")
        if result.stdout.strip():
            self.log("STDOUT:\n" + result.stdout.rstrip())
        if result.stderr.strip():
            self.log("STDERR:\n" + result.stderr.rstrip())
        self.log(f"EXIT CODE: {result.returncode}")

    def browse_repo(self) -> None:
        selected = filedialog.askdirectory(
            title="Select EDL Repo",
            initialdir=self.repo_path_var.get().strip() or str(Path.cwd()),
        )
        if selected:
            self.repo_path_var.set(selected)
            self.open_repo()

    def open_repo(self) -> None:
        if not self.confirm_save_if_dirty("opening a different repository"):
            return

        path_text = self.repo_path_var.get().strip()
        if not path_text:
            messagebox.showerror("Repo Path", "Please provide a repository path.")
            return

        repo_path = Path(path_text)
        if not repo_path.exists():
            messagebox.showerror("Repo Path", f"Path does not exist:\n{repo_path}")
            return

        service = RepoService(repo_path)
        ok, detail = service.validate_structure()
        if not ok:
            messagebox.showerror("Invalid Repo", detail)
            self.log("Invalid repo structure. " + detail.replace("\n", " | "))
            return

        self.service = service
        self.script_availability = service.detect_scripts()

        self.config.default_repo_path = str(repo_path)
        save_config(self.config)

        self.current_file = None
        self.loaded_text = ""
        self.is_dirty = False
        self.validation_failures.clear()
        self.editor_text.configure(state="normal")
        self.editor_text.delete("1.0", "end")
        self.editor_text.configure(state="disabled")
        self.file_status_var.set("No file selected")
        self.lock_detail_var.set("")
        self.duplicate_var.set("Duplicate lines: 0")

        self.log(f"Opened repository: {repo_path}")
        self.refresh_all()

    def refresh_all(self) -> None:
        if not self.service:
            self.update_action_states()
            return

        self.branch_var.set(self.service.git_branch())
        self.user_var.set(self.service.git_user())

        self.script_availability = self.service.detect_scripts()
        if self.script_availability.missing:
            self.script_status_var.set(
                "Missing scripts: " + ", ".join(self.script_availability.missing)
            )
        else:
            self.script_status_var.set("All workflow scripts detected.")

        self.populate_file_list()
        self.refresh_changed_files()
        self.update_action_states()

    def populate_file_list(self) -> None:
        if not self.service:
            return

        selected_before = self.current_file

        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        self.file_index.clear()
        items = self.service.file_items(self.validation_failures, self.search_var.get())
        for file_item in items:
            self.file_index[file_item.name] = file_item
            self.file_tree.insert("", "end", iid=file_item.name, text=file_item.name, values=(file_item.status,))

        if selected_before and selected_before in self.file_index:
            self.file_tree.selection_set(selected_before)
            self.file_tree.focus(selected_before)
        elif self.current_file and self.current_file not in self.file_index:
            self.current_file = None
            self.loaded_text = ""
            self.is_dirty = False
            self.editor_text.configure(state="normal")
            self.editor_text.delete("1.0", "end")
            self.editor_text.configure(state="disabled")
            self.file_status_var.set("No file selected")
            self.lock_detail_var.set("")
            self.duplicate_var.set("Duplicate lines: 0")

    def on_file_selected(self, _event: object = None) -> None:
        selection = self.file_tree.selection()
        if not selection:
            return

        new_file = selection[0]
        if new_file == self.current_file:
            return

        if not self.confirm_save_if_dirty("switching files"):
            if self.current_file and self.current_file in self.file_index:
                self.file_tree.selection_set(self.current_file)
                self.file_tree.focus(self.current_file)
            return

        self.load_file_into_editor(new_file)

    def load_file_into_editor(self, file_name: str) -> None:
        if not self.service:
            return

        try:
            content = self.service.read_working_file(file_name)
        except Exception as exc:
            messagebox.showerror("Open File", f"Failed to open file:\n{exc}")
            self.log(f"Failed to open {file_name}: {exc}")
            return

        self.current_file = file_name
        self.loaded_text = content
        self.is_dirty = False

        self.editor_text.configure(state="normal")
        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", content)
        self.editor_text.edit_modified(False)

        file_item = self.file_index.get(file_name)
        if file_item:
            self.file_status_var.set(f"Selected: {file_name} | Status: {file_item.status}")
            if file_item.lock:
                self.lock_detail_var.set(
                    f"Lock: by {file_item.lock.locked_by} on {file_item.lock.machine} | "
                    f"ticket {file_item.lock.ticket} | {file_item.lock.timestamp}"
                )
            else:
                self.lock_detail_var.set("Lock: none")
        else:
            self.file_status_var.set(f"Selected: {file_name}")
            self.lock_detail_var.set("Lock: unknown")

        self.update_duplicate_summary()
        self.update_action_states()

    def on_editor_modified(self, _event: object = None) -> None:
        self.editor_text.edit_modified(False)
        if not self.current_file:
            return

        current_text = self.editor_text.get("1.0", "end-1c")
        self.is_dirty = current_text != self.loaded_text
        self.update_duplicate_summary()
        self.update_action_states()

    def update_duplicate_summary(self) -> None:
        if not self.service:
            self.duplicate_var.set("Duplicate lines: 0")
            return

        content = self.editor_text.get("1.0", "end-1c")
        duplicates = self.service.duplicate_lines(content)
        if duplicates:
            sample = duplicates[0]
            self.duplicate_var.set(f"Duplicate lines: {len(duplicates)} (e.g. {sample})")
        else:
            self.duplicate_var.set("Duplicate lines: 0")

    def confirm_save_if_dirty(self, reason: str) -> bool:
        if not self.is_dirty:
            return True

        choice = messagebox.askyesnocancel(
            "Unsaved Changes",
            f"You have unsaved changes. Save before {reason}?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_current_file()
        return True

    def save_current_file(self) -> bool:
        if not self.service or not self.current_file:
            return False

        try:
            content = self.editor_text.get("1.0", "end-1c")
            self.service.save_working_file(self.current_file, content)
            self.loaded_text = content
            self.is_dirty = False
            self.log(f"Saved edl/working/{self.current_file}")
            self.refresh_changed_files()
            self.populate_file_list()
            self.update_action_states()
            return True
        except Exception as exc:
            messagebox.showerror("Save Failed", f"Could not save file:\n{exc}")
            self.log(f"Save failed for {self.current_file}: {exc}")
            return False

    def reload_current_file(self) -> None:
        if not self.current_file:
            messagebox.showinfo("Refresh File", "Select a file first.")
            return

        if not self.confirm_save_if_dirty("refreshing this file"):
            return

        self.load_file_into_editor(self.current_file)

    def ensure_ticket(self) -> str | None:
        ticket = self.ticket_var.get().strip()
        if not ticket:
            messagebox.showwarning("Ticket Required", "Enter a ticket/change number first.")
            return None
        return ticket

    def selected_file_required(self) -> str | None:
        if not self.current_file:
            messagebox.showwarning("File Required", "Select a working EDL file first.")
            return None
        return self.current_file

    def checkout_selected(self) -> None:
        if not self.service:
            return
        if not self.script_availability.checkout:
            messagebox.showerror("Checkout", "checkout.ps1 is missing in scripts/.")
            return

        file_name = self.selected_file_required()
        if not file_name:
            return

        ticket = self.ensure_ticket()
        if not ticket:
            return

        result = self.service.run_powershell_script(
            "checkout.ps1",
            ["-FileName", file_name, "-Ticket", ticket],
        )
        self.log_command_result(result)

        if result.ok:
            messagebox.showinfo("Checkout", "Checkout succeeded.")
        else:
            messagebox.showerror("Checkout", "Checkout failed. See activity log for details.")

        self.refresh_all()

    def validate_selected(self) -> bool:
        if not self.service:
            return False
        if not self.script_availability.validate:
            messagebox.showerror("Validate", "validate.ps1 is missing in scripts/.")
            return False

        file_name = self.selected_file_required()
        if not file_name:
            return False

        if not self.confirm_save_if_dirty("running validation"):
            return False

        result = self.service.run_powershell_script(
            "validate.ps1",
            self.validate_args(file_name),
        )
        self.log_command_result(result)

        if result.ok:
            self.validation_failures.discard(file_name)
            messagebox.showinfo("Validate", "Validation succeeded.")
            ok = True
        else:
            self.validation_failures.add(file_name)
            messagebox.showerror("Validate", "Validation failed. See activity log for details.")
            ok = False

        self.refresh_all()
        return ok

    def checkin_selected(self) -> None:
        if not self.service:
            return
        if not self.script_availability.checkin:
            messagebox.showerror("Checkin", "checkin.ps1 is missing in scripts/.")
            return

        file_name = self.selected_file_required()
        if not file_name:
            return

        ticket = self.ensure_ticket()
        if not ticket:
            return

        if not self.validate_selected():
            return

        if not messagebox.askyesno(
            "Confirm Checkin",
            "Checkin will remove the lock when validation passes. Continue?",
        ):
            return

        result = self.service.run_powershell_script(
            "checkin.ps1",
            self.checkin_args(file_name, ticket),
        )
        self.log_command_result(result)

        if result.ok:
            self.validation_failures.discard(file_name)
            messagebox.showinfo("Checkin", "Checkin succeeded.")
        else:
            self.validation_failures.add(file_name)
            messagebox.showerror("Checkin", "Checkin failed. See activity log for details.")

        self.refresh_all()

    def refresh_changed_files(self) -> None:
        self.changed_listbox.delete(0, "end")
        if not self.service:
            return

        for path in self.service.git_changed_files():
            self.changed_listbox.insert("end", path)

    def create_branch(self) -> None:
        if not self.service:
            return
        if not self.service.git_available():
            messagebox.showerror("Git", "Git is not available for this repo path.")
            return

        branch = self.new_branch_var.get().strip()
        if not branch:
            messagebox.showwarning("Branch", "Enter a branch name first.")
            return

        if not messagebox.askyesno("Create Branch", f"Create and switch to branch '{branch}'?"):
            return

        result = self.service.git_command("checkout", "-b", branch)
        self.log_command_result(result)

        if result.ok:
            self.new_branch_var.set("")
            messagebox.showinfo("Branch", "Branch created and checked out.")
        else:
            messagebox.showerror("Branch", "Branch creation failed. See activity log.")

        self.refresh_all()

    def commit_changes(self) -> None:
        if not self.service:
            return
        if not self.service.git_available():
            messagebox.showerror("Git", "Git is not available for this repo path.")
            return

        if self.is_dirty:
            if not self.confirm_save_if_dirty("committing"):
                return

        message = self.commit_message_var.get().strip()
        if not message:
            messagebox.showwarning("Commit", "Enter a commit message first.")
            return

        changed = self.service.git_changed_files()
        if not changed:
            messagebox.showinfo("Commit", "No changed files to commit.")
            return

        preview = "\n".join(changed[:10])
        if len(changed) > 10:
            preview += "\n..."

        if not messagebox.askyesno(
            "Confirm Commit",
            "Commit all current changes with this message?\n\n"
            f"Message: {message}\n\nFiles:\n{preview}",
        ):
            return

        add_result = self.service.git_command("add", "-A")
        self.log_command_result(add_result)
        if not add_result.ok:
            messagebox.showerror("Commit", "git add failed. See activity log.")
            self.refresh_all()
            return

        commit_result = self.service.git_command("commit", "-m", message)
        self.log_command_result(commit_result)

        if commit_result.ok:
            self.commit_message_var.set("")
            messagebox.showinfo("Commit", "Commit succeeded.")
        else:
            messagebox.showerror("Commit", "Commit failed. See activity log.")

        self.refresh_all()

    def push_branch(self) -> None:
        if not self.service:
            return
        if not self.service.git_available():
            messagebox.showerror("Git", "Git is not available for this repo path.")
            return

        branch = self.service.git_branch().strip()
        if not branch or branch.startswith("("):
            messagebox.showerror("Push", "Could not detect active branch.")
            return

        if not messagebox.askyesno("Confirm Push", f"Push branch '{branch}' to origin?"):
            return

        result = self.service.git_command("push", "-u", "origin", branch)
        self.log_command_result(result)

        if result.ok:
            messagebox.showinfo("Push", "Push succeeded.")
        else:
            messagebox.showerror("Push", "Push failed. See activity log.")

        self.refresh_all()

    def build_release(self) -> None:
        if not self.service:
            return
        if not self.script_availability.build_release:
            messagebox.showerror("Build Release", "build-release.ps1 is missing in scripts/.")
            return

        release_id = self.release_id_var.get().strip()
        prompt = "Build release from approved content only?"
        if release_id:
            prompt += f"\n\nRelease ID: {release_id}"

        if not messagebox.askyesno("Confirm Build Release", prompt):
            return

        args: list[str] = []
        if release_id:
            args += ["-ReleaseId", release_id]

        result = self.service.run_powershell_script("build-release.ps1", args)
        self.log_command_result(result)

        if result.ok:
            messagebox.showinfo("Build Release", "Release build succeeded.")
        else:
            messagebox.showerror("Build Release", "Release build failed. See activity log.")

        self.refresh_all()

    def publish_release(self, dry_run: bool) -> None:
        if not self.service:
            return
        if not self.script_availability.publish_release:
            messagebox.showerror("Publish Release", "publish-release.ps1 is missing in scripts/.")
            return

        release_id = self.release_id_var.get().strip()
        if not release_id:
            messagebox.showwarning("Publish Release", "Enter a Release ID first.")
            return

        action = "dry-run publish" if dry_run else "publish"
        if not messagebox.askyesno(
            "Confirm Publish",
            f"Run {action} for release '{release_id}'?",
        ):
            return

        args: list[str] = ["-ReleaseId", release_id]
        destination = self.publish_dest_var.get().strip()
        if destination:
            args += ["-DestinationPath", destination]
        if dry_run:
            args += ["-DryRun"]

        result = self.service.run_powershell_script("publish-release.ps1", args)
        self.log_command_result(result)

        if result.ok:
            messagebox.showinfo("Publish Release", "Publish command completed.")
        else:
            messagebox.showerror("Publish Release", "Publish command failed. See activity log.")

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

    def update_action_states(self) -> None:
        has_service = self.service is not None
        has_file = self.current_file is not None

        checkout_state = "normal" if (has_service and has_file and self.script_availability.checkout) else "disabled"
        validate_state = "normal" if (has_service and has_file and self.script_availability.validate) else "disabled"
        checkin_state = "normal" if (has_service and has_file and self.script_availability.checkin) else "disabled"
        save_state = "normal" if (has_service and has_file and self.is_dirty) else "disabled"

        self.checkout_button.configure(state=checkout_state)
        self.validate_button.configure(state=validate_state)
        self.checkin_button.configure(state=checkin_state)
        self.save_button.configure(state=save_state)
        self.refresh_file_button.configure(state="normal" if (has_service and has_file) else "disabled")

        git_ok = has_service and self.service is not None and self.service.git_available()
        state_git = "normal" if git_ok else "disabled"
        self.create_branch_button.configure(state=state_git)
        self.commit_button.configure(state=state_git)
        self.push_button.configure(state=state_git)

        build_state = "normal" if (has_service and self.script_availability.build_release) else "disabled"
        publish_state = "normal" if (has_service and self.script_availability.publish_release) else "disabled"
        self.build_release_button.configure(state=build_state)
        self.publish_button.configure(state=publish_state)
        self.publish_dry_button.configure(state=publish_state)

    def validate_args(self, file_name: str) -> list[str]:
        args = ["-Path", str(self.service.working_dir / file_name)]
        if self.ignore_comments_var.get():
            args.append("-IgnoreComments")
        return args

    def checkin_args(self, file_name: str, ticket: str) -> list[str]:
        args = ["-FileName", file_name, "-Ticket", ticket]
        if self.ignore_comments_var.get():
            args.append("-IgnoreComments")
        return args

    def on_close(self) -> None:
        if not self.confirm_save_if_dirty("closing the app"):
            return
        self.config.ignore_comments_by_default = self.ignore_comments_var.get()
        save_config(self.config)
        self.root.destroy()


def create_root(theme: str) -> tk.Tk:
    if HAS_TTKBOOTSTRAP and ttkbootstrap is not None:
        return ttkbootstrap.Window(themename=theme)

    root = tk.Tk()
    return root


def run() -> None:
    config = load_config()
    root = create_root(config.theme)
    EDLDesktopApp(root, config)
    root.mainloop()


if __name__ == "__main__":
    run()
