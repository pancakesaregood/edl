# EDL Naming Standard

This standard keeps list files predictable and easy to validate/review.

## Current Fixed List IDs

The current production list IDs are maintained exactly as below for compatibility:

- `Corp_url_whitelist.txt`
- `domainblocklist.txt`
- `greenspace.txt`
- `internet_only_whitelist.txt`
- `ipset_blocklist.txt`
- `skype_teams.txt`
- `nodescrypt.txt`
- `ip_blocklist.txt`
- `url_blocklist.txt`

These are valid even if they do not follow the preferred new-list naming pattern.

## File Name Pattern

Preferred pattern:

```text
<list-kind>-<topic>[-<entry-type>].txt
```

Where:

- `list-kind`: `blocklist` or `allowlist`
- `topic`: security context (for example `malware`, `phishing`, `vendors`)
- `entry-type` (optional but recommended):
  - `ip` for IP/CIDR entries
  - `domain` for FQDN/domain entries
  - `url` for URL entries

Examples:

- `domainblocklist.txt`
- `url_blocklist.txt`
- `Corp_url_whitelist.txt`
- `ip_blocklist.txt`

## Character Rules

- Lowercase letters, numbers, and hyphens only.
- No spaces.
- Use `.txt` extension.
- Keep names short but descriptive.

## Entry Content Expectations

Each line is one entry. Blank lines are allowed. Comments may be included using `#` at line start.

Supported entry formats:

- IP or CIDR: `203.0.113.0/24`, `198.51.100.10`
- Domain/FQDN: `service.example.invalid`
- URL: `https://updates.example.invalid/feed`

## Folder Usage

- `edl/working/<file>.txt`: operator edits
- `edl/approved/<file>.txt`: reviewed source of truth
- `edl/releases/archive/<release-id>/<file>.txt`: built artifact

Use the same base file name across `working` and `approved` to simplify traceability.

## Ticket and Branch Naming

- Ticket IDs: uppercase prefix plus number (for example `CHG-1234`, `INC-2201`)
- Feature branch pattern:

```text
feature/<ticket>-<short-topic>
```

Examples:

- `feature/CHG-1234-phishing-refresh`
- `feature/INC-2201-vendor-fix`

## Release ID Naming

Default build-release format:

```text
release-YYYYMMDD-HHMMSS
```

Example:

- `release-20260416-190000`
