# Debugging Rules

Rules for investigating bugs and reading logs. For detailed CLI references and commands, run:
`python3 scripts/sessions.py context --doc debugging-ref`

---

## Rule 0: Run Health Check First — Mandatory

**Before reading any log or touching any code**, run:

```bash
docker exec api python /app/backend/scripts/debug.py health
```

This checks:

- Local OpenObserve (dev) — reachable and authenticated
- Production Admin Debug API — reachable with a valid API key

**If either check fails**: STOP. Do not proceed with debugging. Report the failure to the user and ask what to do next. Attempting to debug without log access wastes time and produces misleading conclusions.

To check only log access (fastest, exits 1 on failure):

```bash
docker exec api python /app/backend/scripts/debug.py health --log-access
```

---

## Rule 1: State Your Understanding First

Before reading logs, touching code, or asking clarifying questions — write out your understanding of the issue:

- What the user did, what they expected, what actually happened
- Which part of the system you believe is involved and why

Then ask: "Is this correct, or did I misunderstand something?" Do not skip this step.

## Rule 2: Verify Regressions Before Fixing

Check `git log -5 -- <broken-file>` — if none of the recent commits are from your session or a concurrent session, do not attempt a fix. Report to the user instead.

If you cannot confirm the feature worked before your changes, STOP and ASK.

## Rule 3: Ask Clarifying Questions First

Establish two facts before debugging:

1. **Who reported it?** Regular user (via in-app reporter) or admin?
2. **Which server?** Dev or production?

- Regular user reports: do NOT ask for more context — proceed with what's given.
- Admin reports: ask for environment, steps to reproduce, error messages, approximate time.

## Rule 4: Production vs Development

- **Production**: Always use Unified Debug CLI (`docker exec api python /app/backend/scripts/debug.py ...`). Never use local `docker compose logs` for production.
- **Dev**: Use `docker compose` commands directly against local containers.
- The assistant runs on the dev server — `docker compose` commands hit local (dev) containers.

## Rule 5: Service Unavailable During Concurrent Work

If an API call fails with 502 or connection error:

1. Check `docker compose ps` for containers in starting/restarting/exited state
2. Check recent logs for restart activity
3. Wait 15-30s and retry (up to 3-4 times)
4. Only escalate if still down after ~2 minutes with no active restart

## Rule 6: When Logs Don't Explain It

Be specific about what information is missing and why it would help. Don't ask generically for "more context." Name the single most likely missing variable.

## Rule 7: UI Bugs — Ask for Share Link First

Before reproducing a UI bug manually, ask the user for a shared chat/embed link. The share URL lets you inspect actual content and open it directly in Firecrawl without login.

## Rule 8: Endpoint Not Receiving Requests

Check the Caddyfile first (`deployment/dev_server/Caddyfile` or `deployment/prod_server/Caddyfile`). Caddy may be blocking or not forwarding the route.

## Rule 9: Where to Look First

| Problem Type            | Check First                               | Then Check                 |
| ----------------------- | ----------------------------------------- | -------------------------- |
| AI response issues      | `task-worker`, `app-ai-worker`            | `api` (WebSocket logs)     |
| Login/auth failures     | `api`                                     | `cms` (Directus logs)      |
| Payment issues          | `api`                                     | `task-worker` (async jobs) |
| Sync/cache issues       | `api` (PHASE1, SYNC_CACHE)                | `cache` (Dragonfly)        |
| Frontend/client issues  | OpenObserve `job='client-console'` (SQL)  | Browser console            |
| Scheduled task failures | `task-scheduler`                          | `task-worker`              |
| User-specific issues    | `debug.py logs`                           | Specific service logs      |
| Mobile/iPhone issues    | `debug.py logs --browser --device iphone` | `--level error` to narrow  |

### Filtering Browser Logs by Device

Every admin browser session is automatically labeled with a `device_type` derived from its User-Agent string. Supported values: `iphone`, `ipad`, `android`, `windows-phone`, `windows`, `mac`, `linux`, `chromeos`, `unknown`.

```bash
# All logs from iPhone sessions (last 30 min)
docker exec api python /app/backend/scripts/debug.py logs --browser --device iphone

# iPhone errors only
docker exec api python /app/backend/scripts/debug.py logs --browser --device iphone --level error

# iPhone errors on production
docker exec api python /app/backend/scripts/debug.py logs --browser --device iphone --level error --prod

# OpenObserve SQL — manual device query
docker exec api python /app/backend/scripts/debug.py logs --o2 \
  --sql "SELECT _timestamp, message, level, user_email, device_type FROM \"default\" WHERE job='client-console' AND device_type='iphone' ORDER BY _timestamp DESC" \
  --quiet-health
```

The `device_type` label is set by `openobserve_push_service.derive_device_type()` at push time and is stored as an indexed stream label in OpenObserve — no UA string parsing needed at query time.

## Rule 9.1: Start With Token-Efficient OpenObserve Presets

Before dumping long raw logs, run a compact OpenObserve preset first:

- `docker exec api python /app/backend/scripts/debug.py logs --o2 --preset web-app-health --since 60`
- `docker exec api python /app/backend/scripts/debug.py logs --o2 --preset web-search-failures --since 1440`
- `docker exec api python /app/backend/scripts/debug.py logs --o2 --preset api-failed-requests --since 1440`

Use `--raw` only when you need representative sample lines, `--sql` for ad-hoc deep dives, and `--quiet-health` to hide routine `/health` and `/healthz` 200 noise.

## Rule 9.2: Chat Processing Issues — Use the chat-processing Preset

When a user reports a message not being processed, a stuck chat, or a missing AI response, run this first:

- `docker exec api python /app/backend/scripts/debug.py logs --o2 --preset chat-processing --since 30`
- Add `--chat-id <id>` to filter to a specific conversation.

The preset shows pipeline milestones (message_received → ai_dispatched → task_success → ai_response_persisted → message_completed), errors from api/app-ai/task-worker, and a timeline of key events — all in one compact view without raw log dumps.

## Rule 10: Embed Resolution Failures

When AI receives raw embed JSON instead of resolved content: the embed resolution pipeline failed silently. Check `resolve_embed_references_in_content()` in `embed_service.py` — common causes: wrong kwargs (silent TypeError), embed resolved after duplicate-detection, expired Redis key, wrong vault key.

## Rule 11: App Missing from Settings App Store

Check `/v1/health` for the app → if absent, the API didn't discover it at startup (restart `api`). If present but unhealthy, check `app-<id>` container logs. Load reference doc for full diagnostic steps.

## Rule 12: Vercel Build Failures

**Never use `vercel logs`** — it returns nothing for ERROR-state deployments. Always use the REST API wrapper:

```bash
python3 backend/scripts/debug.py vercel           # errors/warnings only (fastest)
python3 backend/scripts/debug.py vercel --all     # full build log
python3 backend/scripts/debug.py vercel --n 3     # last 3 deployments
python3 backend/scripts/debug.py vercel --url <deployment-id>  # specific deployment
```

Reads `VERCEL_TOKEN` from `.env`. Works for both READY and ERROR deployments. Also available as `python3 scripts/sessions.py debug-vercel` (auto-starts a session).
