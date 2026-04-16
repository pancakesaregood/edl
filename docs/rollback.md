# Rollback Workflow

This document defines how to safely revert firewall ingest to a prior known-good EDL release.

## Rollback Principle

Rollback is a **publish action**, not an edit action.

- Do not modify `edl/working` for emergency rollback.
- Do not copy from `edl/approved` directly to firewall ingest.
- Re-publish a prior release from `edl/releases/archive/<release-id>/`.

## When to Roll Back

Typical triggers:

- Firewall policy impact after release publish
- Unexpected block/allow behavior
- Validation gap discovered post-release

## Inputs Needed

- Target rollback release ID (for example `release-20260415-221500`)
- Publish destination path used by firewall ingest
- Incident/change ticket ID for audit trail

## Rollback Steps

1. Identify last known-good release ID from `edl/releases/archive/`.
2. Dry-run publish to confirm file set.
3. Execute publish.
4. Confirm firewall ingest picked up new files.
5. Log rollback in ticket/incident and Git history as needed.

Example:

```powershell
# Dry-run validation of rollback package
./scripts/publish-release.ps1 -ReleaseId release-20260415-221500 -DestinationPath D:\fw-ingest\edl -DryRun

# Execute rollback publish
./scripts/publish-release.ps1 -ReleaseId release-20260415-221500 -DestinationPath D:\fw-ingest\edl
```

## Verification Checklist

- [ ] Published release ID matches intended rollback target.
- [ ] `manifest.json` exists at destination.
- [ ] Destination file list matches manifest.
- [ ] Firewall ingest job reports successful refresh.
- [ ] Security operations confirms expected behavior restoration.

## Post-Rollback Actions

1. Open or update incident/change ticket with rollback release ID and UTC timestamp.
2. Create follow-up branch to correct approved content.
3. Build and publish a corrected forward release after review.

## Optional Audit Commit

If your team tracks rollback events in Git, add a lightweight note file under `docs/` or release notes folder with:

- release rolled back from/to
- date/time (UTC)
- operator/reviewer
- ticket reference
