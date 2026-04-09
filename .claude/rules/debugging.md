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

## Issue Resolution — Delegate to Subagents

**Always prefer the specialist subagents over running `debug.py` inline.** They isolate the noisy timeline output and return compact structured reports:

- **`issue-forensics`** — for any user-reported issue ID. Runs `debug.py issue --timeline`, correlates browser↔backend events, git-blames suspects, returns root-cause hypothesis + suspect files. Use via `/debug-issue` skill or spawn directly.
- **`encryption-flow-tracer`** — for any symptom involving "content decryption failed", key mismatch, cross-device sync bugs, or the `multi-tab-encryption` / `multi-session-encryption` specs. Pre-loaded with the 5 encryption architecture docs. Spawn alongside `issue-forensics` when symptoms point at E2EE.
- **`test-failure-triager`** — for any failing Playwright/vitest/pytest run. Reads all failure reports and returns ranked root-cause groups. Use via `/fix-tests` or `/fix-next-test`.

Only fall back to running these commands yourself if the subagents are unavailable:

```bash
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline
docker exec api python /app/backend/scripts/debug.py issue <id>
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline --production
```

After user confirms fix: `docker exec api python /app/backend/scripts/debug.py issue <id> --delete --yes`

For full debugging guide: `python3 scripts/sessions.py context --doc debugging`

## Default Assumptions

- Issues are on the **dev server**, reported by an **admin**
- Check `git log -5 -- <broken-file>` to see if your session caused the issue
- For unreported issues (e.g. "signup failed last night"), use `debug.py trace errors --route <pattern> --last <window>` — no issue report needed
