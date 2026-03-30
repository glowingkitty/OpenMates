---
description: Bug investigation and issue resolution workflow
globs:
---

## Distributed Tracing (OTel)

Use `debug.py trace` **first** for performance issues, error investigation, and request lifecycle debugging. Traces show exact timing and service call chains.

```bash
# Recent errors with full trace context
docker exec api python /app/backend/scripts/debug.py trace errors --last 1h
# Errors on a specific route (e.g. failed signups)
docker exec api python /app/backend/scripts/debug.py trace errors --last 24h --route /v1/auth/register
# Slow requests (>500ms)
docker exec api python /app/backend/scripts/debug.py trace slow --threshold 500 --last 1h
# All traces for a user session
docker exec api python /app/backend/scripts/debug.py trace session --user someone@example.com --last 2h
# Login flow trace
docker exec api python /app/backend/scripts/debug.py trace login --user someone@example.com
# Specific trace by ID (from error logs or issue reports)
docker exec api python /app/backend/scripts/debug.py trace request --id <trace-id>
# Celery task trace
docker exec api python /app/backend/scripts/debug.py trace task --id <celery-task-uuid>
```

All commands support `--production` and `--json` flags.

**When to use traces vs logs:** Traces show request flow, timing, and service boundaries. Logs show application-level detail (error messages, state changes). Use traces to find *where* the problem is, then logs to understand *why*.

## Issue Resolution

```bash
# Unified browser + backend timeline from OpenObserve (now includes OTel trace spans)
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline
# Compact timeline — extracts KEY SIGNALS (errors, decryption/IndexedDB anomalies), last 50 events
# Use this when full timeline is too large (>10KB triggers tool output truncation)
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline --compact
# List N most recent unprocessed issues (default 5), optionally with timeline
docker exec api python /app/backend/scripts/debug.py issue --recent 5
docker exec api python /app/backend/scripts/debug.py issue --recent 3 --timeline --compact
# Metadata, decrypted fields, S3 YAML (includes shared link key validation)
docker exec api python /app/backend/scripts/debug.py issue <id>
# Production issues
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline --production
```

After user confirms fix: `docker exec api python /app/backend/scripts/debug.py issue <id> --delete --yes`

For full debugging guide: `python3 scripts/sessions.py context --doc debugging`

## Default Assumptions

- Issues are on the **dev server**, reported by an **admin**
- Check `git log -5 -- <broken-file>` to see if your session caused the issue
- For unreported issues (e.g. "signup failed last night"), use `debug.py trace errors --route <pattern> --last <window>` — no issue report needed
