# Debugging Guide

Load this document when investigating bugs, reading logs, or troubleshooting Docker services.

---

## CRITICAL: Verify a Regression Before Attempting to Fix It

Before spending any effort debugging a suspected regression, confirm it is actually caused by recent changes.

**Step 1: Check whether your session (or a concurrent session) touched the broken code**

```bash
git log -5 -- <file-that-contains-the-broken-code>
```

If none of the recent commits are from your session or a concurrent session, **do not attempt a fix** — report to the user instead.

**Step 2: Verify the feature worked before your changes**

```bash
git show <last-commit-before-yours>:<path/to/file> | grep -A5 -B5 "relevant function"
```

**Step 3: If you cannot confirm it was working before — STOP and ASK**

Say: "I cannot confirm this was working before my changes — it may be a pre-existing issue. How would you like me to proceed?"

It is always better to ask than to spend multiple test cycles trying to fix something that was broken long before your session started.

---

## CRITICAL: Ask Clarifying Questions Before Debugging

**Before touching any logs or code, you MUST establish the following two facts:**

1. **Who reported the issue?** — Was it a regular user (via the in-app issue reporter) or an admin?
2. **Which server?** — Did the issue occur on the **dev** server or **production**?

### Decision Tree

```
Issue source?
├── Reported by a REGULAR USER (via in-app issue reporter)
│   └── Do NOT ask the user for more context — they cannot provide it beyond what is in the report.
│       Instead, read the issue report carefully and proceed with what is given.
│       → Still confirm with the admin presenting the issue: dev or production?
│
└── Reported by an ADMIN (directly in this chat)
    └── Ask the following clarifying questions BEFORE starting any investigation:
        1. "Was this issue on the dev server or production?"
        2. "Can you share any additional context — steps to reproduce, error messages,
           approximate time it happened, or the user account affected?"
        Then wait for answers before proceeding.
```

### Why This Matters

- **Dev vs production** determines which debugging tools to use (local `docker compose` vs Admin Debug CLI).
  Getting this wrong wastes time investigating the wrong environment.
- **Admin vs user report** determines whether asking follow-up questions is useful.
  A regular user's issue report contains everything available — pushing the admin to ask the user for more
  information rarely yields actionable details and delays investigation.

### Minimum Required Context Before Debugging

| Context Item          | Required?    | Source                              |
| --------------------- | ------------ | ----------------------------------- |
| Dev or production?    | Always       | Ask admin if not obvious from issue |
| Admin or user report? | Always       | Visible from issue report metadata  |
| Error message / logs  | If available | Check issue report or ask admin     |
| Approximate time      | Helpful      | Ask admin (narrows log search)      |
| Affected user/chat ID | Helpful      | Often in issue report               |

**Only proceed to log investigation after you have at minimum: dev-or-production confirmed.**

---

## CRITICAL: Production vs Development Debugging

**ALWAYS determine which server the issue is on FIRST.** The `dev` branch runs on the development server; the `main` branch runs on production. These are completely separate environments.

> **Architecture reminder:** The assistant (Claude Code) executes **directly on the dev server** — the same machine that runs the Docker containers. This means:
>
> - `docker compose` commands and `docker exec` commands run against **local containers and the local database** — this IS the dev environment.
> - `api.dev.openmates.org` is the public-facing URL of this same dev server. There is no separate dev database; the local PostgreSQL container is the dev database.
> - To access **production**, you must use the Admin Debug CLI (which sends HTTP requests to `api.openmates.org` over the network) — never `docker compose` for production.

### Production Server Debugging (ALWAYS use Admin Debug CLI)

**For production issues, ALWAYS use the Admin Debug CLI** (`backend/scripts/admin_debug_cli.py`). This script runs locally on the dev server via `docker exec` but queries the **production API** remotely. Do NOT use local `docker compose logs` commands — those only show dev server logs.

```bash
# Query production task-worker logs (last 30 min)
docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services task-worker --since 30

# Search production logs for errors
docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services api,task-worker --search "ERROR|WARNING" --since 60

# Query production task lifecycle events (e.g. to verify a Celery task ran)
docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services task-worker --since 15 --search "TASK_LIFECYCLE"

# Inspect a production user
docker exec api python /app/backend/scripts/admin_debug_cli.py user someone@example.com

# Inspect a production chat
docker exec api python /app/backend/scripts/admin_debug_cli.py chat <chat_id>

# List production issues
docker exec api python /app/backend/scripts/admin_debug_cli.py issues
```

**Key flags:**

- By default, the CLI targets **production** (`https://api.openmates.org`)
- Add `--dev` to target the development server instead
- Add `--json` for raw JSON output
- Add `--lines 500` to increase log output (default: 100, max: 500)

**Available commands:** `logs`, `issues`, `issue <id>`, `issue-delete <id>`, `user <email>`, `chat <id>`, `embed <id>`, `requests`, `newsletter`

**When to also check production code:** If something should be working but isn't (e.g., a task was queued but never executed), check whether the code exists on the `main` branch:

```bash
git fetch origin main
git grep "function_or_task_name" main
git show main:path/to/file.py
```

### Development Server Debugging (Local Docker Compose)

**For dev server issues, use `docker compose` commands directly** — these read logs from the local Docker containers.

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs <service-name>              # View logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f <service-name>          # Follow logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=100 <service-name>  # Last 100 lines
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f -t <service-name>       # With timestamps
```

### Time-Based Log Filtering (Dev Server Only)

```bash
# Logs from the last N minutes
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 5m api task-worker

# Logs from the last hour
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 1h api
```

### Log Level Filtering (Dev Server Only)

```bash
# Only errors and warnings
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail 500 api | rg -E "ERROR|WARNING|CRITICAL"

# Errors with context
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 10m api task-worker | rg -B3 -A3 "ERROR"
```

---

## Service Unavailable During Concurrent Work

Multiple assistants may work on the codebase simultaneously. If an API call or test fails with a connection error, 502, or similar "service unavailable" symptom, **do not immediately assume a real bug**. Another assistant may be rebuilding or restarting containers at that moment.

### Protocol When a Service Appears Down

1. **Check container status first:**

   ```bash
   docker compose --env-file .env -f backend/core/docker-compose.yml ps
   ```

   Look for containers in `starting`, `restarting`, or `exited` state.

2. **Check recent logs for restart/build activity:**

   ```bash
   # See if the container recently started (build + restart in progress)
   docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 2m api task-worker
   ```

   Signs of an in-progress restart: log lines like `Booting worker`, `Application startup complete`, `Waiting for application startup`, or build output.

3. **Wait and retry — don't give up immediately:**
   - If logs show a restart is in progress, wait 15–30 seconds and retry.
   - Repeat up to 3–4 times before concluding the service is genuinely broken.

   ```bash
   sleep 20 && curl -f http://localhost:8000/health
   ```

4. **Only escalate if the service is still down after ~2 minutes** with no active restart activity in the logs. At that point, investigate as a real failure using the standard debugging steps below.

---

## Debugging Backend Issues

### Where to Look First (by Problem Type)

| Problem Type            | Check First                    | Then Check                    |
| ----------------------- | ------------------------------ | ----------------------------- |
| AI response issues      | `task-worker`, `app-ai-worker` | `api` (WebSocket logs)        |
| Login/auth failures     | `api`                          | `cms` (Directus logs)         |
| Payment issues          | `api`                          | `task-worker` (async jobs)    |
| Sync/cache issues       | `api` (PHASE1, SYNC_CACHE)     | `cache` (Dragonfly)           |
| Frontend/client issues  | Loki `{job="client-console"}`  | Browser console (manual)      |
| WebSocket disconnects   | `api`                          | Loki `{job="client-console"}` |
| Scheduled task failures | `task-scheduler`               | `task-worker`                 |
| User data issues        | `cms`, `cms-database`          | `api`                         |

### Debugging Embed Resolution Failures

When the AI receives raw embed JSON (e.g. `{"type": "location", "embed_id": "16c2b7c5-..."}`) instead of resolved content, the embed resolution pipeline failed silently. Symptoms: AI searches for a UUID string, mentions unrelated cities, or gives a nonsensical answer about the embed content.

**Pipeline:**

```
Client insert → EmbedStore (memory + Redis, encrypted with user_vault_key_id)
  → On send: serialised as {"type": "location", "embed_id": "..."}
  → Server: resolve_embed_references_in_content(content, user_vault_key_id, log_prefix)
  → Redis lookup: embed:{id} → decrypt → TOON block → LLM context
```

**Correct function signature** (any deviation causes a silent `TypeError` caught by `except Exception`):

```python
resolve_embed_references_in_content(
    content=content_plain,
    user_vault_key_id=user_vault_key_id,
    log_prefix=f"[Chat {chat_id}]"
)
# NOT: resolve_embed_references_in_content(chat_id=..., user_id=..., encryption_service=...)
```

**Key files:**

- Resolution logic: `backend/core/api/app/services/embed_service.py` → `resolve_embed_references_in_content()` and `_get_cached_embed_toon()`
- Where it's called for the current user message: `backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py` (resolve _before_ adding to history and before duplicate-detection)

**Common failure modes:**

- Wrong kwargs passed to `resolve_embed_references_in_content()` — silent `TypeError` swallowed by broad `except Exception`, falls back to raw JSON
- Embed resolved _after_ the duplicate-detection check — unresolved content never matches already-resolved history entries, causing the same message to appear twice in the LLM context
- Embed key expired in Redis (TTL passed since the user composed the message)
- Wrong `user_vault_key_id` (key mismatch → decryption returns `None`)

**How to verify:** Use `inspect_last_requests.py` to dump the AI request payload and check whether the history contains TOON blocks (`\`\`\`toon\n...\`\`\``) or raw `{"embed_id": "..."}` JSON strings. Raw JSON = resolution failed.

---

### Quick Debug Commands

```bash
# Check if AI response updated sync cache
docker compose --env-file .env -f backend/core/docker-compose.yml logs task-worker --since 5m | rg "SYNC_CACHE_UPDATE.*AI response"

# Monitor Phase 1 sync in real-time
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api | rg "PHASE1"

# Trace full request lifecycle for a specific chat
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker --since 10m | rg -E "chat_id=<ID>|SYNC_CACHE|PHASE1" | head -100
```

### Rebuilding and Restarting Services

If a container might have outdated code after a simple restart, or if you need to ensure a clean state (including clearing the cache volume), use this full rebuild and restart command:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api cms cms-database cms-setup task-worker task-scheduler app-ai app-code app-web app-videos app-news app-maps app-ai-worker app-web-worker cache vault vault-setup prometheus cadvisor loki promtail && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

### Available Docker Containers

**Core services:** `api`, `cms`, `cms-database`, `cms-setup`, `task-worker`, `task-scheduler`

**App services:** `app-ai`, `app-web`, `app-videos`, `app-news`, `app-maps`, `app-code`, `app-audio`, `app-travel`, `app-jobs`, `app-reminder`, `app-pdf`, `app-docs`, `app-images`, `app-openmates`, `app-health`, `app-ai-worker`, `app-web-worker`

**Infrastructure:** `cache`, `vault`, `vault-setup`, `prometheus`, `cadvisor`, `loki`, `promtail`

---

## App Missing from Settings App Store

If an app with skills is **not showing in the settings app store**, the most likely cause is that the app's health status is unknown or unhealthy. The app store only shows apps with skills if they appear as `healthy` in `/v1/health`.

### Diagnostic steps

**Step 1: Check `/v1/health` for the missing app**

```bash
curl -s https://api.dev.openmates.org/v1/health | python3 -m json.tool | grep -A8 '"<app_id>"'
```

- If the app is **absent** from the `apps` section → the `api` container didn't discover it at startup (or the health check task hasn't run yet). See Step 2.
- If the app is present but `"status": "unhealthy"` → the `app-<id>` container is down. See Step 3.

**Step 2: App absent from `/v1/health` entirely**

The `api` discovers apps at startup by calling `http://app-<id>:8000/metadata`. If the app container wasn't running at startup time, the app won't be in `app.state.discovered_apps_metadata` and gets filtered out of `/v1/health`.

```bash
# Check if the app container is up and reachable
docker exec api curl -s http://app-<id>:8000/health

# Check what's in the Redis discovery cache
docker exec api python3 -c "
import asyncio, json, sys
sys.path.insert(0, '/app')
from backend.core.api.app.services.cache import CacheService
async def main():
    c = CacheService()
    client = await c.client
    val = await client.get('discovered_apps_metadata_v1')
    print('Apps in cache:', list(json.loads(val).keys()) if val else 'EMPTY')
asyncio.run(main())
"
```

If the container is healthy but missing from the cache, trigger a health check task to force re-discovery:

```bash
docker exec api python3 -c "
import sys; sys.path.insert(0, '/app')
from backend.core.api.app.tasks.health_check_tasks import check_all_apps_health
check_all_apps_health.apply()
print('Done')
"
```

The `/v1/health` endpoint now also reads `discovered_apps_metadata_v1` from Redis (in addition to `app.state`), so after the task runs the app should appear in `/v1/health` without restarting the API.

If the task runs successfully but the app is still missing from `/v1/health`, restart the `api` container:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml restart api
```

**Step 3: App present but `"status": "unhealthy"`**

```bash
# Check the app container logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=50 app-<id>
```

**Step 4: Verify the frontend appsMetadata has skills for this app**

`appsMetadata.ts` is generated at build time from `backend/apps/<id>/app.yml`. Apps with no production skills have `skills: []` and bypass the health filter entirely (always shown). Apps with production skills require health to be `healthy`.

```bash
# Confirm skills are listed in appsMetadata.ts (generated file, not committed)
grep -A5 '"<app_id>"' frontend/packages/ui/src/data/appsMetadata.ts
```

If the app has `skills: []` but `app.yml` has production skills, regenerate:

```bash
cd frontend/packages/ui && npm run generate-apps-metadata
```

Note: `appsMetadata.ts` is gitignored — it is regenerated automatically by the Vercel build from `app.yml`. No commit needed.

---

## Debugging Frontend Issues (Client Console Logs)

**Admin users only** — browser console logs are automatically forwarded to Loki via `clientLogForwarder.ts`. Regular users' logs are **never** collected or stored. This only works when an admin has the app open in their browser.

### Querying Client Logs via Loki

```bash
# All admin client logs (last 30 min)
docker exec api python /app/backend/scripts/inspect_frontend_logs.py

# Only errors from the last hour
docker exec api python /app/backend/scripts/inspect_frontend_logs.py --level error --since 60

# Filter by admin user
docker exec api python /app/backend/scripts/inspect_frontend_logs.py --user jan41139

# Search log content
docker exec api python /app/backend/scripts/inspect_frontend_logs.py --search "WebSocket"

# Combine filters
docker exec api python /app/backend/scripts/inspect_frontend_logs.py --level error --user jan41139 --since 60

# Raw JSON output
docker exec api python /app/backend/scripts/inspect_frontend_logs.py --json

# Follow mode (poll every 5s, like tail -f)
docker exec api python /app/backend/scripts/inspect_frontend_logs.py --follow
```

### Key Loki Labels

| Label        | Values                           | Description           |
| ------------ | -------------------------------- | --------------------- |
| `job`        | `client-console`                 | Always this value     |
| `level`      | `debug`, `info`, `warn`, `error` | Console log level     |
| `user_email` | Admin username (e.g. `jan41139`) | Which admin's browser |
| `server_env` | `development`, `production`      | Which environment     |
| `source`     | `browser`                        | Always this value     |

### How It Works

- `clientLogForwarder.ts` subscribes to `logCollector.onNewLog()`, buffers entries, and POSTs batches every 5s to `POST /v1/admin/client-logs`
- Only activates when `is_admin === true` (checked on both client and server)
- Regular users are **never** affected — no logs are collected or sent
- Log messages are sanitized by `logCollector.ts` before forwarding (API keys, tokens, passwords redacted)
- Each log entry includes `[tab=<id>] [<pageUrl>]` prefix for multi-tab disambiguation

### Key Files

- Client forwarder: `frontend/packages/ui/src/services/clientLogForwarder.ts`
- Log collector (with sanitization): `frontend/packages/ui/src/services/logCollector.ts`
- Backend endpoint: `backend/core/api/app/routes/admin_client_logs.py`
- Loki push service: `backend/core/api/app/services/loki_push_service.py`

---

## Docker Debug Mode

### Overview

When debugging in Docker Compose environments, debug logging instrumentation must account for containerized execution paths and volume mounts.

### Volume Mount Configuration

Add this mount to services that may execute code with debug instrumentation:

```yaml
volumes:
  - ../../.cursor:/app/.cursor
```

### Log Path in Containers

- **Container path**: `/app/.cursor/debug.log`
- **Host path**: `{workspace_root}/.cursor/debug.log`

### Non-Blocking Debug Logging

All debug logging instrumentation MUST be wrapped in try-except blocks:

```python
# #region agent log
try:
    import json
    import os
    log_path = '/app/.cursor/debug.log'
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        f.write(json.dumps({...})+'\n')
except Exception:
    pass  # Non-blocking: debug logging failure should not break functionality
# #endregion
```

### Verification

After adding volume mounts:

1. Restart affected services: `docker-compose restart <service-name>`
2. Verify the mount: `docker exec <container-name> ls -la /app/.cursor`
3. Test debug logging by triggering the instrumented code path

---

## Vercel Deployment Verification (Frontend)

**IMPORTANT:** After every `git push origin dev` that includes frontend changes, verify the Vercel deployment succeeded. The frontend (`open-mates-webapp`) is deployed automatically by Vercel on push.

### Checking Deployment Status

```bash
# List recent deployments — check the latest one's status
vercel ls open-mates-webapp 2>&1 | head -10

# Expected: ● Ready (success) or ● Building (in progress)
# Problem:  ● Error (build failed)
```

### Getting Build Logs for Failed Deployments

```bash
# Get the deployment URL from `vercel ls`, then inspect build logs:
vercel inspect --logs <deployment-url> 2>&1 | tail -80

# Example:
vercel inspect --logs https://open-mates-webapp-2ktsb5tu0-marcos-projects-e740a395.vercel.app 2>&1 | tail -80
```

### Getting Runtime Logs (for successful deployments)

```bash
# Runtime logs are only available for deployments with status ● Ready
vercel logs <deployment-url> 2>&1
```

### Common Build Failures

| Error Pattern                                              | Cause                          | Fix                                                         |
| ---------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------- |
| `'onsubmit\|preventDefault' is not a valid attribute name` | Svelte 4 event modifier syntax | Use `onsubmit={(e) => { e.preventDefault(); handler(e); }}` |
| `'on:click' is not a valid attribute name`                 | Svelte 4 `on:` event syntax    | Use `onclick={handler}`                                     |
| `export let` errors                                        | Svelte 4 prop syntax           | Use `let { prop } = $props()`                               |
| `$:` reactive statement errors                             | Svelte 4 reactivity            | Use `$derived()` or `$effect()`                             |
| `Command failed with exit code 1`                          | General build error            | Check the lines above for the specific error                |

### Post-Push Verification Workflow

After pushing frontend changes to `dev`:

1. **Wait ~30 seconds** for Vercel to pick up the push
2. **Check deployment status:** `vercel ls open-mates-webapp 2>&1 | head -5`
3. **If status is ● Error:** Get build logs with `vercel inspect --logs <url> 2>&1 | tail -80`
4. **Fix the error**, commit, and push again
5. **If status is ● Ready:** Deployment succeeded — verify at https://open-mates-webapp-git-dev-marcos-projects-e740a395.vercel.app
