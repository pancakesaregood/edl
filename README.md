# Firewall EDL Controlled Content Pipeline (MVP)

This repository provides a simple, auditable workflow for managing firewall External Dynamic List (EDL) text files using GitLab and PowerShell.

## Objectives

- Keep editable source files separate from approved and released artifacts.
- Use lock files to reduce concurrent edits to the same working file.
- Validate EDL content before check-in and before release.
- Build immutable, timestamped release packages with hashes.
- Publish only from a built release package (never from `edl/working` or `edl/approved`).

## Repository Layout

```text
edl/
  working/            # operator edits
  approved/           # reviewed source of truth for release builds
  releases/
    current/          # latest built release artifact
    archive/          # timestamped release history
locks/                # transient lock files created by checkout/checkin scripts
docs/                 # process documentation
scripts/              # operational automation scripts
```

## Roles and Responsibilities

- Operator:
  - edits only `edl/working/*`
  - uses checkout/checkin scripts
  - opens GitLab MR for review
- Reviewer:
  - reviews changes and validation results
  - approves promotion from `working` to `approved`
- Release Manager:
  - builds release from `edl/approved`
  - publishes selected release to ingest location

## Maintained Lists

The following list files are maintained and support checkout/checkin workflow:

- `Corp_url_whitelist.txt`
- `domainblocklist.txt`
- `greenspace.txt`
- `internet_only_whitelist.txt`
- `ipset_blocklist.txt`
- `skype_teams.txt`
- `nodescrypt.txt`
- `ip_blocklist.txt`
- `url_blocklist.txt`

## Validation Model

- Each list file is validated as a single entry type (one type per file).
- File-to-type mapping is defined in [`edl/list-types.json`](edl/list-types.json).
- URL-based lists use URL pattern validation:
  - `*` is accepted as a wildcard.
  - `/` is used to anchor path patterns.
  - Example: `*.corp.example.invalid/apps/*`

## Script Summary

- `scripts/checkout.ps1`:
  - creates lock file in `locks/` for one working file
- `scripts/checkin.ps1`:
  - validates target file
  - removes lock file on success
- `scripts/validate.ps1`:
  - validates one file or all files
  - checks format and duplicates
- `scripts/build-release.ps1`:
  - builds timestamped archive release from approved only
  - refreshes `edl/releases/current`
  - writes `manifest.json` with hashes
- `scripts/publish-release.ps1`:
  - publishes a release from `edl/releases/archive/<release-id>`
  - supports dry-run mode

## Safety Rules

- Firewall ingest location must consume only published release output.
- Do not configure firewall ingest to pull from `edl/working`.
- Do not configure firewall ingest to pull from `edl/approved`.
- Use GitLab merge requests for approvals.

## Operator Quickstart

```powershell
# 1) Create a branch
git checkout -b feature/CHG-1234-domainblocklist-update

# 2) Checkout a working file (creates lock)
./scripts/checkout.ps1 -FileName domainblocklist.txt -Ticket CHG-1234

# 3) Edit file under edl/working/
# (use your editor)

# 4) Validate file
./scripts/validate.ps1 -Path edl/working/domainblocklist.txt -IgnoreComments

# 5) Check in file (validates + removes lock)
./scripts/checkin.ps1 -FileName domainblocklist.txt -Ticket CHG-1234 -IgnoreComments

# 6) Commit and open GitLab MR
git add .
git commit -m "feat(edl): CHG-1234 update domainblocklist"
git push -u origin feature/CHG-1234-domainblocklist-update
```

See [docs/process.md](docs/process.md) for full workflow, branch strategy, MR checklist, release process, and reviewer steps.

## Local Windows Desktop Tool

This repo now includes a local Python desktop app for endpoint operators:

- package: `desktop_app`
- launcher: `launch-edl-desktop.bat`
- entrypoint: `python -m desktop_app`
- config: `desktop_app/app_config.json` (default repo path + UI options)

The app is endpoint-local (not a web app) and wraps existing repo scripts and Git commands.

### Features

- Repo path picker and refresh
- EDL working file browser with search and status
- Lock-awareness from `locks/*.lock.json`
- In-app editing for `edl/working/*.txt` only
- Checkout / Validate / Checkin using existing PowerShell scripts
- Git branch, changed files, commit, and push helpers
- Guarded release actions (build/publish) in separate panel
- Activity log with command stdout/stderr and export option

### Setup (Windows)

```powershell
# From repo root
py -3 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

If `ttkbootstrap` is unavailable, the app falls back to standard Tkinter styling.

### GitLab Token (Per User)

Each operator and reviewer should use their own GitLab token for HTTPS remotes.

- Preferred: paste token into the app `GitLab Token` field and click `Use Token` (session only).
- Alternative: set environment variable `GITLAB_TOKEN` before launching the app.
- `GitLab User` defaults to `oauth2`; change it only if your GitLab server policy requires a different username.
- Tokens are not written to repo files or app config.

### Run

```powershell
# Preferred
py -3 -m desktop_app

# Or use the launcher
./launch-edl-desktop.bat
```

### Packaging (Optional)

You can package the app as a single Windows executable with PyInstaller:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --noconsole --name edl-desktop-tool desktop_app\\__main__.py
```

Generated executable is typically under `dist/edl-desktop-tool.exe`.

### Desktop Tool Assumptions

- Operator has local access to a checked-out repo clone.
- Python 3 is installed on the workstation.
- PowerShell scripts exist in `scripts/` for checkout/checkin/validate (release scripts optional).
- Git is installed and on `PATH` for branch/commit/push actions.
- Users edit only files under `edl/working`; approved/release paths are not editable in-app.

## Local Windows Reviewer Tool

This repo also includes a separate reviewer-only desktop app for sign-off:

- package: `reviewer_app`
- launcher: `launch-edl-reviewer.bat`
- entrypoint: `python -m reviewer_app`
- config: `reviewer_app/app_config.json`

The reviewer app focuses on review and approval decisions, not operator editing.

### Reviewer Features

- Open local repo and fetch latest changes
- Tabbed workspace to reduce clutter:
  - `Review`
  - `GitLab`
  - `Release`
  - `Logs`
- Show changed `edl/working/*.txt` files needing review
- Filter/search changed file list with statuses:
  - `pending review`
  - `approved`
  - `rejected`
  - `validation failed`
  - `ready for release`
- Show lock info if lock file exists
- Show baseline vs proposed content and unified line diff
- Re-run validation using `scripts/validate.ps1`
- Approve / reject with decision safeguards:
  - approve requires reviewer name, ticket, and passing validation
  - reject requires reviewer name, ticket, and note
- GitLab-native reviewer flow:
  - connect to GitLab URL + project using per-user token
  - load open merge requests (optionally only those assigned to current reviewer)
  - approve merge requests in GitLab (role/permission dependent)
  - remove approval, add review notes, and open MR in browser
- Persist reviewer decisions to JSON sign-off artifacts
- Optional guarded promotion to `edl/approved`
- Optional guarded release build/publish controls (if scripts exist)
- Activity log + command details including exact command and stdout/stderr

### Reviewer Sign-Off Artifacts

Decision metadata is stored per file in:

- `review-decisions/<file-key>.json`

Each record contains:

- `filename`
- `ticket`
- `decision`
- `reviewer`
- `timestamp`
- `notes`
- `source_branch`
- `latest_commit_hash`
- `base_ref`
- `validation_ok`

### Reviewer Run

```powershell
# Preferred
py -3 -m reviewer_app

# Or launcher
./launch-edl-reviewer.bat
```

Reviewer fetch actions against HTTPS remotes also require per-user token setup (`Use Token` or `GITLAB_TOKEN`).

### Reviewer Packaging (Optional)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --noconsole --name edl-reviewer-tool reviewer_app\\__main__.py
```

## Troubleshooting Breadcrumbs

Both desktop apps now write a persistent per-session diagnostic log automatically:

- Operator logs: `logs/operator/operator-<timestamp>-<user>-<host>.log`
- Reviewer logs: `logs/reviewer/reviewer-<timestamp>-<user>-<host>.log`

The UI also includes an `Open Log Folder` button. On command failures and unexpected UI exceptions, dialogs include the exact diagnostic log path.

When troubleshooting with me, send:

1. The diagnostic `.log` file for the failed run.
2. The failing action you clicked (for example `Validate`, `Checkin`, `Fetch Latest`).
3. Approximate local timestamp of failure.

### Reviewer Assumptions and Repo Gaps

- This repo had no formal reviewer sign-off schema before; `review-decisions/*.json` is the lightweight local audit mechanism now used.
- Decision records are local repo artifacts and should be committed with the review branch for full traceability.
- Changed-file review scope is derived from Git diff against a base ref (default `origin/main`) plus local working tree changes.
- The tool does not perform GitLab API calls; it is endpoint-local and Git CLI driven.

## Separation Enforcement

This repository intentionally ships two separate desktop tools with separate UI flows:

- Operator app: [`desktop_app`](/E:/edl/desktop_app)
  - checkout, edit, validate, checkin, commit, push
- Reviewer app: [`reviewer_app`](/E:/edl/reviewer_app)
  - diff inspection, re-validation, approve/reject, sign-off recording, guarded release prep

Reviewer actions are not merged into the operator editing screen, and reviewer sign-off metadata is stored under [`review-decisions`](/E:/edl/review-decisions).

## GitLab End-State Rollout

Use this repo model as the endpoint-local client for your work GitLab project:

1. Create a GitLab project for this repository structure.
2. Protect `main` and require merge requests.
3. Require reviewer approval rules for EDL changes.
4. Grant operator users `Developer` role (no direct merge to protected branch).
5. Grant reviewer/release users approval rights per your GitLab policy.
6. Enforce branch naming (for example `feature/<ticket>-<topic>`).
7. Optionally add GitLab CI to run `scripts/validate.ps1 -All -IgnoreComments` on MR.
8. Have users clone the GitLab project locally and point each app to that local clone path.

Recommended local launch pattern on reviewer/operator endpoints:

- Operator: `py -3 -m desktop_app` or `launch-edl-desktop.bat`
- Reviewer: `py -3 -m reviewer_app` or `launch-edl-reviewer.bat`

This keeps all editing and review actions local/auditable while GitLab remains the approval and source-of-truth system.
