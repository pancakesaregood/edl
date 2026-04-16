# EDL Process Workflow

This document defines the day-to-day operating model for EDL content in this repository.

## Managed Lists (Current)

These list files are the controlled set currently maintained in this GitLab repository:

- `Corp_url_whitelist.txt`
- `domainblocklist.txt`
- `greenspace.txt`
- `internet_only_whitelist.txt`
- `ipset_blocklist.txt`
- `skype_teams.txt`
- `nodescrypt.txt`
- `ip_blocklist.txt`
- `url_blocklist.txt`

## Core Concepts

- **Checkout** means acquiring an edit lock for one file in `edl/working/`.
- **Checkin** means validating the edited file and releasing the lock.
- **Lock file** means a JSON file in `locks/` that records who has the file checked out.
- **Approved** means reviewer-accepted content in `edl/approved/`.
- **Release** means generated artifacts in `edl/releases/archive/<release-id>/` and `edl/releases/current/`.
- **Published** means copied release output to the firewall ingest location.

## GitLab Token Access (Per User)

- Each operator/reviewer should use their own GitLab token for this project.
- For desktop tools, enter token in the app and click `Use Token` (session-only), or set `GITLAB_TOKEN` before launch.
- Use GitLab HTTPS remotes with protected branches and MR approval policy.
- Do not share tokens between users.

## Directory Responsibilities

- `edl/working`: editable by operators.
- `edl/approved`: updated only by reviewed/approved changes.
- `edl/releases/*`: generated artifacts only, never hand-edited.
- `locks`: transient lock metadata created by scripts.

## Per-File Type Enforcement

- Every `.txt` list has exactly one expected entry type.
- Type map file: `edl/list-types.json`.
- `validate.ps1` uses this map by default.
- URL list types support pattern syntax:
  - `*` wildcard matching
  - `/` anchored path matching
  - example: `*.example.invalid/path/*`

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
6. Commit and open merge request (MR).

Example:

```powershell
git checkout main
git pull
git checkout -b feature/CHG-1234-domainblocklist-refresh

./scripts/checkout.ps1 -FileName domainblocklist.txt -Ticket CHG-1234
# edit edl/working/domainblocklist.txt
./scripts/validate.ps1 -Path edl/working/domainblocklist.txt -IgnoreComments
./scripts/checkin.ps1 -FileName domainblocklist.txt -Ticket CHG-1234 -IgnoreComments

git add edl/working/domainblocklist.txt
git commit -m "feat(edl): CHG-1234 refresh domainblocklist"
git push -u origin feature/CHG-1234-domainblocklist-refresh
```

## Reviewer Workflow

1. Review GitLab MR diff and ticket reference.
2. Re-run validation locally.
3. Confirm no malformed entries or duplicates.
4. Confirm lock files are not committed.
5. Approve MR.
6. Merge to `main`.
7. Promote reviewed content from `working` to `approved` in controlled MR (or same MR if your policy allows).

Promotion example:

```powershell
Copy-Item edl/working/domainblocklist.txt edl/approved/domainblocklist.txt -Force
git add edl/approved/domainblocklist.txt
git commit -m "promote(edl): CHG-1234 domainblocklist approved"
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
./scripts/validate.ps1 -Path edl/working/ip_blocklist.txt -IgnoreComments

# Validate URL pattern list with wildcard and anchored path entries
./scripts/validate.ps1 -Path edl/working/url_blocklist.txt -IgnoreComments

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

- `feature/CHG-1234-domainblocklist-refresh`
- `feature/INC-2201-ip-blocklist-fix`
- `release/release-20260416-190000`

## Merge Request Checklist (GitLab Example)

- [ ] Ticket/change ID is present in branch name and MR description.
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

- `feat(edl): CHG-1234 refresh domainblocklist`
- `fix(edl): INC-2201 remove duplicate ip_blocklist entry`
- `promote(edl): CHG-1234 approve url_blocklist update`
- `release(edl): REL-20260416 build release-20260416-190000`
