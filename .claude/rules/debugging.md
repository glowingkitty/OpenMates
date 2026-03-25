---
description: Bug investigation and issue resolution workflow
globs:
---

## Issue Resolution

```bash
# Unified browser + backend timeline from OpenObserve
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline
# Metadata, decrypted fields, S3 YAML
docker exec api python /app/backend/scripts/debug.py issue <id>
# Production issues
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline --production
```

After user confirms fix: `docker exec api python /app/backend/scripts/debug.py issue <id> --delete --yes`

For full debugging guide: `python3 scripts/sessions.py context --doc debugging`

## Default Assumptions

- Issues are on the **dev server**, reported by an **admin**
- Check `git log -5 -- <broken-file>` to see if your session caused the issue
