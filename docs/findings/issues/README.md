# Reported Issue Findings

Durable findings notes for user-reported issues live under this directory.

## Workflow

Use the reported issue database as the source of truth:

```bash
python3 scripts/issues.py list --env prod --limit 20
python3 scripts/issues.py show <issue-id> --env prod
python3 scripts/issues.py findings <issue-id> --env prod
python3 scripts/issues.py timeline <issue-id> --env prod --compact
```

Create or update the findings note before changing product code. The note records the first anomaly, root-cause hypothesis, related reports, attempts, tests, and final verification.

## Layout

Notes are stored by environment and report year:

```text
docs/findings/issues/<env>/<YYYY>/<issue-id>-<title-slug>.md
```

Supported environments are `prod` and `dev`. Share URL encryption fragments are redacted as `#key=<redacted>` by default.

## Status And Links

Use frontmatter updates rather than editing metadata by hand when possible:

```bash
python3 scripts/issues.py mark <issue-id> --env prod --status investigating
python3 scripts/issues.py link <issue-id> --env prod --github '#123' --linear OPE-512
```

Keep private user data, secrets, screenshots, raw decrypted content, and unredacted share keys out of these notes.
