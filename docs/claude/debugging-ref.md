# Debugging Reference

Detailed CLI commands, log queries, and diagnostic procedures.
Load on demand: `python3 scripts/sessions.py context --doc debugging-ref`

---

## Unified Debug CLI (Production)

```bash
# Query production logs (last 30 min)
docker exec api python /app/backend/scripts/debug.py logs --services task-worker --since 30

# Search production logs for errors
docker exec api python /app/backend/scripts/debug.py logs --services api,task-worker --search "ERROR|WARNING" --since 60

# Inspect a production user
docker exec api python /app/backend/scripts/debug.py user someone@example.com

# Inspect a production chat
docker exec api python /app/backend/scripts/debug.py chat <chat_id>

# List production issues
docker exec api python /app/backend/scripts/debug.py issue --list
```

**Key flags:** Default target: production. `--dev` for dev server. `--json` for raw output. `--lines 500` (max).

**Available commands:** `logs`, `upload-logs`, `preview-logs`, `upload-update`, `preview-update`, `issues`, `issue <id>`, `issue-delete <id>`, `user <email>`, `chat <id>`, `embed <id>`, `requests`, `newsletter`

**Issue inspection:**

| Command                                       | What it shows                                                                                                         |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `issue <id>`                                  | Metadata + decrypted fields + S3 YAML (IndexedDB, HTML snapshots, runtime state, action history, screenshot URL)      |
| `issue <id> --timeline`                       | **Unified browser + backend log timeline from OpenObserve** — use this instead of `--full-logs` for log investigation |
| `issue <id> --timeline --before 15 --after 5` | Custom window: 15 min before / 5 min after report (defaults: 10/5)                                                    |
| `issue <id> --timeline --production`          | Same, via production Admin Debug API (`GET /issues/{id}/timeline`)                                                    |
| `issue <id> --no-logs`                        | Metadata + decrypted fields only (skip S3 YAML fetch, fastest)                                                        |
| `issue --list`                                | List recent unprocessed issues                                                                                        |

The `--timeline` flag queries OpenObserve live — no S3 access needed. It runs three parallel SQL queries anchored to `issue.created_at`:

1. `job=client-issue-report AND issue_id=<id>` — browser console snapshot pushed at report time
2. `job=container-logs` — backend containers mentioning `issue_id` or `user_id`
3. `job=api-logs` — API logs mentioning same terms

The S3 YAML no longer stores `console_logs` or `docker_compose_logs` (stripped as of `a4ccddcff`). Old YAMLs still containing them show a 40-line error-only quick scan with a pointer to `--timeline`.

---

## Upload / Preview Server Debugging

```bash
docker exec api python /app/backend/scripts/debug.py upload-logs
docker exec api python /app/backend/scripts/debug.py upload-logs --services app-uploads,clamav --since 30 --search "ERROR"
docker exec api python /app/backend/scripts/debug.py preview-logs --since 30 --lines 200
docker exec api python /app/backend/scripts/debug.py upload-update   # returns 202, monitor with logs
docker exec api python /app/backend/scripts/debug.py preview-update
```

Allowed services for `upload-logs`: `app-uploads`, `clamav`, `vault`

---

## Development Server Debugging (Prefer OpenObserve via `debug.py`)

Use OpenObserve-backed `debug.py` commands first for local dev debugging. Fall back to `docker compose logs` only when OpenObserve/Promtail is unavailable, for very early startup crashes, or when diagnosing the logging stack itself.

```bash
# Preset-based overview (fast, token-efficient)
docker exec api python /app/backend/scripts/debug.py logs --o2 --preset web-app-health --since 60
docker exec api python /app/backend/scripts/debug.py logs --o2 --preset api-failed-requests --since 60

# Service-focused deep dive with SQL
docker exec api python /app/backend/scripts/debug.py logs --o2 \
  --sql "SELECT _timestamp, service, level, message FROM \"default\" WHERE job='container-logs' AND service IN ('api','task-worker') ORDER BY _timestamp DESC LIMIT 200" \
  --quiet-health
```

Fallback (`docker compose logs`) commands:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs <service>
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f <service>
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=100 <service>
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 5m api task-worker
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail 500 api | rg -E "ERROR|WARNING|CRITICAL"
```

---

## Quick Debug Commands

```bash
# Check if AI response updated sync cache
docker compose --env-file .env -f backend/core/docker-compose.yml logs task-worker --since 5m | rg "SYNC_CACHE_UPDATE.*AI response"

# Monitor Phase 1 sync in real-time
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api | rg "PHASE1"

# Trace request lifecycle for a specific chat
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker --since 10m | rg -E "chat_id=<ID>|SYNC_CACHE|PHASE1" | head -100
```

---

## Full Stack Rebuild

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api cms cms-database cms-setup task-worker task-scheduler app-ai app-code app-web app-videos app-news app-maps app-ai-worker app-web-worker cache vault vault-setup prometheus cadvisor openobserve promtail && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

**Available Docker Containers:**

- Core: `api`, `cms`, `cms-database`, `cms-setup`, `task-worker`, `task-scheduler`
- Apps: `app-ai`, `app-web`, `app-videos`, `app-news`, `app-maps`, `app-code`, `app-audio`, `app-travel`, `app-jobs`, `app-reminder`, `app-pdf`, `app-docs`, `app-images`, `app-openmates`, `app-health`, `app-ai-worker`, `app-web-worker`
- Infra: `cache`, `vault`, `vault-setup`, `prometheus`, `cadvisor`, `openobserve`, `promtail`

---

## App Missing from Settings — Full Diagnostic

**Step 1:** Check `/v1/health`:

```bash
curl -s https://api.dev.openmates.org/v1/health | python3 -m json.tool | grep -A8 '"<app_id>"'
```

**Step 2:** If absent — check container and Redis cache:

```bash
docker exec api curl -s http://app-<id>:8000/health
```

Force re-discovery:

```bash
docker exec api python3 -c "
import sys; sys.path.insert(0, '/app')
from backend.core.api.app.tasks.health_check_tasks import check_all_apps_health
check_all_apps_health.apply()
print('Done')
"
```

If still missing, restart `api`.

**Step 3:** If present but unhealthy — check app logs with OpenObserve first:

`docker exec api python /app/backend/scripts/debug.py logs --o2 --sql "SELECT _timestamp, service, level, message FROM \"default\" WHERE job='container-logs' AND service='app-<id>' ORDER BY _timestamp DESC LIMIT 50" --quiet-health`

Fallback: `docker compose logs --tail=50 app-<id>`

**Step 4:** Verify frontend `appsMetadata.ts`: `grep -A5 '"<app_id>"' frontend/packages/ui/src/data/appsMetadata.ts`

Regenerate if needed: `cd frontend/packages/ui && npm run generate-apps-metadata`

---

## Vercel Deployment Debugging

**Never use `vercel logs`** — it returns nothing for ERROR-state deployments. Always use the REST API wrapper:

```bash
python3 backend/scripts/debug.py vercel           # errors/warnings only (fastest)
python3 backend/scripts/debug.py vercel --all     # full build log
python3 backend/scripts/debug.py vercel --n 3     # last 3 deployments
python3 backend/scripts/debug.py vercel --url <deployment-id>  # specific deployment
# Or via sessions.py (auto-starts a session):
python3 scripts/sessions.py debug-vercel
```

| Symptom             | Likely Cause             | Diagnose                 |
| ------------------- | ------------------------ | ------------------------ |
| `ERROR` status      | Build failure            | `debug.py vercel --all`  |
| 404 on routes       | Adapter misconfiguration | `debug.py vercel`        |
| Runtime crash (500) | Missing env var          | `debug.py vercel`        |
| App blank           | Client-side JS error     | Firecrawl or OpenObserve |

Do NOT run `vercel build` locally. Fix code → push → auto-deploys.

---

## Browser-Based Debugging with Firecrawl

```
firecrawl_browser_create
→ agent-browser open https://app.dev.openmates.org
→ agent-browser snapshot -i -c
→ [reproduce bug]
→ agent-browser screenshot
[fix → rebuild/push]
→ [verify fix]
→ agent-browser screenshot
```

### Client-side state inspection:

```
agent-browser executeScript "window.debug()"
agent-browser executeScript "await window.debug.chat('<chat-id>')"
agent-browser executeScript "await window.debug.embed('<embed-id>')"
agent-browser executeScript "window.debug.help()"
```

Full `window.debug` API: `debug()`, `help()`, `chat(id)`, `chat(id, {download:true})`, `chatVerbose(id)`, `chats()`, `message(id)`, `embed(id)`, `decrypt(embedId)`, `logs(n)`, `state()`

---

## Chat Processing Preset (OpenObserve)

Diagnose stuck chats, missing AI responses, or pipeline failures in one command:

```bash
# Last 30 minutes (all chats)
docker exec api python /app/backend/scripts/debug.py logs --o2 --preset chat-processing --since 30

# Filter to a specific chat ID
docker exec api python /app/backend/scripts/debug.py logs --o2 --preset chat-processing --since 60 --chat-id <chat_id>
```

Output shows:

- **Pipeline milestones** — which stages completed: `message_received → vault_key → ai_dispatched → task_started → task_success → ai_response_persisted → chat_persisted → suggestions_persisted → sync_cache_updated → message_completed`
- **Errors** from `api`, `app-ai`, and `task-worker` services
- **Warnings** (first 5)
- **Key events timeline** — important log lines in chronological order

Services queried: `api` (200 hits), `app-ai` (100 hits), `task-worker` (200 hits) in parallel from the `default` OpenObserve stream.

---

## Client Console Logs (Admin Only via OpenObserve)

```bash
docker exec api python /app/backend/scripts/debug.py logs --browser
docker exec api python /app/backend/scripts/debug.py logs --browser --level error --since 60
docker exec api python /app/backend/scripts/debug.py logs --browser --user jan41139
docker exec api python /app/backend/scripts/debug.py logs --browser --follow
```

OpenObserve SQL (direct query — requires admin credentials):

```bash
NOW=$(date +%s%6N) && SINCE=$((NOW - 3600000000)) && \
docker exec api curl -s -u "admin@openmates.internal:<password>" \
  -H "Content-Type: application/json" \
  -d "{\"query\":{\"sql\":\"SELECT _timestamp, user_email, level, message FROM \\\"default\\\" WHERE job='client-console' ORDER BY _timestamp DESC LIMIT 50\",\"start_time\":${SINCE},\"end_time\":${NOW},\"from\":0,\"size\":50}}" \
  "http://openobserve:5080/api/default/_search"
```

Fields: `job=client-console`, `level=debug|info|warn|error`, `user_email=<admin>`, `server_env=development|production`

Key files: `clientLogForwarder.ts`, `logCollector.ts`, `admin_client_logs.py`, `openobserve_push_service.py`

---

## Decrypting Client-Side Content (Share Key)

```bash
# Full share URL
docker exec api python /app/backend/scripts/debug.py chat <chat_id> \
  --share-url "https://app.openmates.org/share/chat/<chat_id>#key=<blob>"

# Password-protected
docker exec api python /app/backend/scripts/debug.py chat <chat_id> \
  --share-url "..." --share-password "the-password"

# Raw blob only
docker exec api python /app/backend/scripts/debug.py chat <chat_id> --share-key "<base64-key-blob>"

# Embed share URL
docker exec api python /app/backend/scripts/debug.py embed <embed_id> \
  --share-url "https://app.openmates.org/share/embed/<embed_id>#key=<blob>"

# Combine client-side + server-side decryption
docker exec api python /app/backend/scripts/debug.py chat <chat_id> --decrypt --share-url "..."
```

Share URL formats: `https://app.openmates.org/share/chat/<id>#key=<blob>`, `https://app.openmates.org/share/embed/<id>#key=<blob>`, dev: `https://app.dev.openmates.org/share/...`

Crypto implementation: `backend/scripts/debug_utils.py (Section 10)`, mirrors `shareEncryption.ts`, `embedShareEncryption.ts`, `cryptoService.ts`

---

## Production Inspection (`--production` flag)

```bash
docker exec api python /app/backend/scripts/debug.py chat <chat_id> --production
docker exec api python /app/backend/scripts/debug.py chat <chat_id> --production --share-url "..."
docker exec api python /app/backend/scripts/debug.py embed <embed_id> --production
docker exec api python /app/backend/scripts/debug.py chat <chat_id> --dev
```

| Feature                       | Available? |
| ----------------------------- | ---------- |
| `--share-url` / `--share-key` | Yes        |
| `--decrypt` (Vault)           | No         |
| `--check-links`               | No         |

---

## Embed Resolution — Detailed Pipeline

```
Client insert → EmbedStore (memory + Redis, encrypted)
  → On send: {"type": "location", "embed_id": "..."}
  → Server: resolve_embed_references_in_content(content, user_vault_key_id, log_prefix)
  → Redis lookup → decrypt → TOON block → LLM context
```

Correct signature:

```python
resolve_embed_references_in_content(
    content=content_plain,
    user_vault_key_id=user_vault_key_id,
    log_prefix=f"[Chat {chat_id}]"
)
```

Key files: `embed_service.py` → `resolve_embed_references_in_content()`, `message_received_handler.py`

Verify: `debug.py requests` — check for TOON blocks vs raw JSON.

---

## Docker Debug Mode

Volume mount: `../../.cursor:/app/.cursor`

Non-blocking logging:

```python
# #region agent log
try:
    import json, os
    with open('/app/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({...})+'\n')
except Exception:
    pass
# #endregion
```
