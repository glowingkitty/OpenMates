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
- **`e2e-test-investigator`** — for deep investigation of a **specific** failing E2E spec. Reads screenshots (ground truth — error messages often lie), queries OpenObserve client+backend logs, traces spec code through frontend components, identifies root cause, and proposes or applies a fix. Use when `test-failure-triager` has identified the failing spec but you need to understand *why* it fails. Spawn one per failing spec for parallel investigation.

Only fall back to running these commands yourself if the subagents are unavailable:

```bash
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline
docker exec api python /app/backend/scripts/debug.py issue <id>
docker exec api python /app/backend/scripts/debug.py issue <id> --timeline --production
```

After user confirms fix: `docker exec api python /app/backend/scripts/debug.py issue <id> --delete --yes`

For full debugging guide: `python3 scripts/sessions.py context --doc debugging`

## Ad-hoc Log Queries (`--query-json`)

For structured ad-hoc log searches that don't fit a canned preset, use `--query-json` with a JSON body matching `LogQueryRequest` (`backend/core/api/app/routes/admin_debug.py`). Works on **both dev and prod** through the same CLI — dev talks directly to local OpenObserve (no auth), prod goes over HTTPS to the admin endpoint (uses the admin API key from Vault). The old `--sql` flag was removed because its prod fallback silently routed to the canned `/errors/logs` top-errors endpoint and ignored the filter entirely.

**Whitelists:** streams `default` and `client_console`. Operators: `eq, neq, like, not_like, in, gt, gte, lt, lte`. Modes: `select` (raw rows) and `count_by` (GROUP BY + COUNT). Hard caps: `limit <= 1000`, `since_minutes <= 10080`, 15 filters max. Every call is audit-logged at WARNING with the `[ADMIN_LOG_QUERY]` prefix. See the module docstring in `admin_debug.py` for the full security model (no user SQL ever reaches OpenObserve — all SQL is composed server-side from whitelisted identifiers + SQL-escaped literals).

```bash
# Search for a specific substring across all backend logs on prod
docker exec api python /app/backend/scripts/debug.py logs --prod --o2 --query-json \
  '{"stream":"default","filters":[{"field":"message","op":"like","value":"%passkey%"}],"since_minutes":1440,"limit":20}'

# Count errors by service+level on dev (last 24h)
docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json \
  '{"stream":"default","mode":"count_by","group_by":["service","level"],"filters":[{"field":"level","op":"in","value":["ERROR","CRITICAL"]}],"since_minutes":1440,"limit":15}'

# Browser console logs for a specific debugging session
docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json \
  '{"stream":"client_console","filters":[{"field":"debugging_id","op":"eq","value":"dbg-abc123"}],"since_minutes":60,"limit":50}'

# Timeline for a specific user id on prod
docker exec api python /app/backend/scripts/debug.py logs --prod --o2 --query-json \
  '{"stream":"default","filters":[{"field":"message","op":"like","value":"%<user-id-prefix>%"}],"since_minutes":1440,"limit":100}'
```

**When to use presets vs `--query-json`:** Presets (`--preset top-warnings-errors`, `--preset api-failed-requests`, etc.) for recurring health checks. `--query-json` for ad-hoc investigation with specific filter terms. Both are token-efficient compared to the user-timeline mode (`debug.py logs <email>`).

## Default Assumptions

- Issues are on the **dev server**, reported by an **admin**
- Check `git log -5 -- <broken-file>` to see if your session caused the issue
- For unreported issues (e.g. "signup failed last night"), use `debug.py trace errors --route <pattern> --last <window>` — no issue report needed
