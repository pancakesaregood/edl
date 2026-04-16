# Firewall EDL Controlled Content Pipeline (MVP)

This repository provides a simple, auditable workflow for managing firewall External Dynamic List (EDL) text files using Git and PowerShell.

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
  - opens PR for review
- Reviewer:
  - reviews changes and validation results
  - approves promotion from `working` to `approved`
- Release Manager:
  - builds release from `edl/approved`
  - publishes selected release to ingest location

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
- Use pull requests / merge requests for approvals.

## Operator Quickstart

```powershell
# 1) Create a branch
git checkout -b feature/CHG-1234-malware-edl-update

# 2) Checkout a working file (creates lock)
./scripts/checkout.ps1 -FileName blocklist-malware.txt -Ticket CHG-1234

# 3) Edit file under edl/working/
# (use your editor)

# 4) Validate file
./scripts/validate.ps1 -Path edl/working/blocklist-malware.txt -IgnoreComments

# 5) Check in file (validates + removes lock)
./scripts/checkin.ps1 -FileName blocklist-malware.txt -Ticket CHG-1234 -IgnoreComments

# 6) Commit and open PR
git add .
git commit -m "feat(edl): CHG-1234 update malware blocklist"
```

See [docs/process.md](docs/process.md) for full workflow, branch strategy, PR checklist, release process, and reviewer steps.
