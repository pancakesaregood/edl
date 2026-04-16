# EDL Process Workflow

This document defines the day-to-day operating model for EDL content in this repository.

## Core Concepts

- **Checkout** means acquiring an edit lock for one file in `edl/working/`.
- **Checkin** means validating the edited file and releasing the lock.
- **Lock file** means a JSON file in `locks/` that records who has the file checked out.
- **Approved** means reviewer-accepted content in `edl/approved/`.
- **Release** means generated artifacts in `edl/releases/archive/<release-id>/` and `edl/releases/current/`.
- **Published** means copied release output to the firewall ingest location.

## Directory Responsibilities

- `edl/working`: editable by operators.
- `edl/approved`: updated only by reviewed/approved changes.
- `edl/releases/*`: generated artifacts only, never hand-edited.
- `locks`: transient lock metadata created by scripts.

## Lock File Behavior

`checkout.ps1` creates `locks/<file>.lock.json` with:

- `file_name`
- `locked_by`
- `machine`
- `ticket`
- `timestamp`

Rules:

- If lock exists, checkout fails.
- Checkin requires matching ticket and user.
- Lock is removed only after successful validation.

## Operator Workflow

1. Create branch from `main`.
2. Checkout file lock.
3. Edit file under `edl/working`.
4. Validate.
5. Check in (validation + lock removal).
6. Commit and open PR.

Example:

```powershell
git checkout main
git pull
git checkout -b feature/CHG-1234-phishing-refresh

./scripts/checkout.ps1 -FileName blocklist-phishing.txt -Ticket CHG-1234
# edit edl/working/blocklist-phishing.txt
./scripts/validate.ps1 -Path edl/working/blocklist-phishing.txt -IgnoreComments
./scripts/checkin.ps1 -FileName blocklist-phishing.txt -Ticket CHG-1234 -IgnoreComments

git add edl/working/blocklist-phishing.txt
git commit -m "feat(edl): CHG-1234 refresh phishing blocklist"
git push -u origin feature/CHG-1234-phishing-refresh
```

## Reviewer Workflow

1. Review PR diff and ticket reference.
2. Re-run validation locally.
3. Confirm no malformed entries or duplicates.
4. Confirm lock files are not committed.
5. Approve PR.
6. Merge to `main`.
7. Promote reviewed content from `working` to `approved` in controlled PR (or same PR if your policy allows).

Promotion example:

```powershell
Copy-Item edl/working/blocklist-phishing.txt edl/approved/blocklist-phishing.txt -Force
git add edl/approved/blocklist-phishing.txt
git commit -m "promote(edl): CHG-1234 phishing list approved"
```

## Release Workflow

1. Ensure `main` is up to date and approved content is present.
2. Build release from approved content only.
3. Verify release manifest and hashes.
4. Publish selected release to ingest path.

Example:

```powershell
./scripts/build-release.ps1
# capture returned release ID, for example release-20260416-184500

./scripts/publish-release.ps1 -ReleaseId release-20260416-184500 -DryRun
./scripts/publish-release.ps1 -ReleaseId release-20260416-184500 -DestinationPath D:\fw-ingest\edl
```

## Publish Rules

- Publishing source must be `edl/releases/archive/<release-id>/` only.
- Never publish directly from `edl/working`.
- Never publish directly from `edl/approved`.
- Use `-DryRun` before actual copy when possible.

## Day-to-Day Command Reference

```powershell
# Validate one file
./scripts/validate.ps1 -Path edl/working/blocklist-malware.txt -IgnoreComments

# Validate all working + approved files
./scripts/validate.ps1 -All -IgnoreComments

# Build explicit release ID
./scripts/build-release.ps1 -ReleaseId release-20260416-190000

# Publish explicit release
./scripts/publish-release.ps1 -ReleaseId release-20260416-190000 -DestinationPath D:\fw-ingest\edl
```

## Branch Strategy (Example)

- `main`: protected branch, reviewed merges only.
- `feature/<ticket>-<short-topic>`: operator change branches.
- Optional `release/<release-id>`: release prep or release note branch.

Examples:

- `feature/CHG-1234-phishing-refresh`
- `feature/INC-2201-vendor-allowlist-fix`
- `release/release-20260416-190000`

## Pull Request Checklist (Example)

- [ ] Ticket/change ID is present in branch name and PR description.
- [ ] Edited files are under `edl/working` (and `edl/approved` only if promoting approved content).
- [ ] `./scripts/validate.ps1` passes.
- [ ] No duplicates in EDL entries.
- [ ] No lock files are committed from `locks/*.lock.json`.
- [ ] Commit messages follow repository format.
- [ ] Reviewer confirmed promotion logic from `working` to `approved`.

## Commit Message Format (Example)

Format:

```text
<type>(edl): <ticket> <summary>
```

Examples:

- `feat(edl): CHG-1234 refresh phishing blocklist`
- `fix(edl): INC-2201 remove duplicate vendor domain`
- `promote(edl): CHG-1234 approve malware list update`
- `release(edl): REL-20260416 build release-20260416-190000`
