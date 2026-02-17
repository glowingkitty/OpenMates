# Debugging Guide

Load this document when investigating bugs, reading logs, or troubleshooting Docker services.

---

## Debugging Backend Issues

**ALWAYS use docker compose terminal commands to check logs** when debugging backend issues.

### Basic Log Commands

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs <service-name>              # View logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f <service-name>          # Follow logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=100 <service-name>  # Last 100 lines
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f -t <service-name>       # With timestamps
```

### Time-Based Log Filtering

```bash
# Logs from the last N minutes
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 5m api task-worker

# Logs from the last hour
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 1h api
```

### Log Level Filtering

```bash
# Only errors and warnings
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail 500 api | rg -E "ERROR|WARNING|CRITICAL"

# Errors with context
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 10m api task-worker | rg -B3 -A3 "ERROR"
```

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
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api cms cms-database cms-setup task-worker task-scheduler app-ai app-code app-web app-videos app-news app-maps app-ai-worker app-web-worker cache vault vault-setup prometheus cadvisor loki promtail grafana && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

### Available Docker Containers

**Core services:** `api`, `cms`, `cms-database`, `cms-setup`, `task-worker`, `task-scheduler`

**App services:** `app-ai`, `app-web`, `app-videos`, `app-news`, `app-maps`, `app-code`, `app-ai-worker`, `app-web-worker`

**Infrastructure:** `cache`, `vault`, `vault-setup`, `prometheus`, `cadvisor`, `loki`, `promtail`, `grafana`

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

| Error Pattern | Cause | Fix |
|---|---|---|
| `'onsubmit\|preventDefault' is not a valid attribute name` | Svelte 4 event modifier syntax | Use `onsubmit={(e) => { e.preventDefault(); handler(e); }}` |
| `'on:click' is not a valid attribute name` | Svelte 4 `on:` event syntax | Use `onclick={handler}` |
| `export let` errors | Svelte 4 prop syntax | Use `let { prop } = $props()` |
| `$:` reactive statement errors | Svelte 4 reactivity | Use `$derived()` or `$effect()` |
| `Command failed with exit code 1` | General build error | Check the lines above for the specific error |

### Post-Push Verification Workflow

After pushing frontend changes to `dev`:

1. **Wait ~30 seconds** for Vercel to pick up the push
2. **Check deployment status:** `vercel ls open-mates-webapp 2>&1 | head -5`
3. **If status is ● Error:** Get build logs with `vercel inspect --logs <url> 2>&1 | tail -80`
4. **Fix the error**, commit, and push again
5. **If status is ● Ready:** Deployment succeeded — verify at https://open-mates-webapp-git-dev-marcos-projects-e740a395.vercel.app