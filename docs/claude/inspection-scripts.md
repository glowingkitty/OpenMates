# Server Inspection Scripts

Load this document when you need to inspect chats, users, issues, cache, or AI requests on the server. Run all commands from the repo root.

---

## Unified Debug Entry Point (`debug.py`)

`backend/scripts/debug.py` is the single command to use for all common debugging tasks. It shows health summaries by default and delegates to the individual inspect scripts when full detail is needed.

```bash
# Quick system health check (Prometheus metrics, Loki error count, Celery queue depth)
docker exec api python /app/backend/scripts/debug.py

# Full health with verbose metrics and recent errors
docker exec api python /app/backend/scripts/debug.py health -v

# Chat health summary (fast — status, versions, message count, embed count)
docker exec api python /app/backend/scripts/debug.py chat <chat_id>

# Full chat inspection (messages, embeds, keys, cache, decryption)
docker exec api python /app/backend/scripts/debug.py chat <chat_id> -v
docker exec api python /app/backend/scripts/debug.py chat <chat_id> -v --decrypt
docker exec api python /app/backend/scripts/debug.py chat <chat_id> --prod

# Embed health summary / full inspection
docker exec api python /app/backend/scripts/debug.py embed <embed_id>
docker exec api python /app/backend/scripts/debug.py embed <embed_id> -v --decrypt
docker exec api python /app/backend/scripts/debug.py embed <embed_id> --prod

# User health summary / full inspection
docker exec api python /app/backend/scripts/debug.py user <email>
docker exec api python /app/backend/scripts/debug.py user <email> -v

# User activity log timeline (Loki cross-service)
docker exec api python /app/backend/scripts/debug.py logs <email>
docker exec api python /app/backend/scripts/debug.py logs <email> --since 120 --level warning
docker exec api python /app/backend/scripts/debug.py logs <email> --follow

# Recent AI requests
docker exec api python /app/backend/scripts/debug.py requests
docker exec api python /app/backend/scripts/debug.py requests -v
docker exec api python /app/backend/scripts/debug.py requests --errors-only
docker exec api python /app/backend/scripts/debug.py requests --show-prompt 3

# Issue reports
docker exec api python /app/backend/scripts/debug.py issue --list
docker exec api python /app/backend/scripts/debug.py issue <issue_id>
docker exec api python /app/backend/scripts/debug.py issue <issue_id> -v
docker exec api python /app/backend/scripts/debug.py issue <issue_id> --delete

# Replay a full request trace by request_id (Loki)
docker exec api python /app/backend/scripts/debug.py replay <request_id>

# Top error fingerprints (Redis sorted set + Loki log samples)
docker exec api python /app/backend/scripts/debug.py errors
docker exec api python /app/backend/scripts/debug.py errors --top 20
```

The individual `inspect_*.py` scripts still work for full detail; `debug.py` wraps them with health-first defaults and a unified interface.

---

## Chat, Embed and User Inspection

```bash
# Inspect a specific chat (cache, storage, Directus)
docker exec api python /app/backend/scripts/inspect_chat.py <chat_id>

# Inspect a specific demo chat
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1

# Inspect a specific embed
docker exec api python /app/backend/scripts/inspect_embed.py <embed_id>

# Inspect daily inspiration state for a user (cache + Directus)
docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id>

# Skip Directus (cache-only, faster)
docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --no-directus

# Skip Redis cache (Directus records only)
docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --no-cache

# List all users currently eligible for daily generation (scans Redis)
docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py --list-active

# JSON output
docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --json
docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py --list-active --json

# Inspect a specific issue report (decrypts all fields, fetches S3 YAML report)
# NOTE: The "Chat/Embed URL" field may show a /share/chat/... URL. This does NOT mean the
# user is reporting an issue with a shared chat they opened. It means the user OWNS that chat
# and voluntarily shared it so you can inspect it — necessary because chats are zero-knowledge
# encrypted and otherwise inaccessible. Treat it as a regular user chat, not a shared/foreign chat.
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id>

# List recent unprocessed issues
docker exec api python /app/backend/scripts/inspect_issue.py --list

# List issues with search and include processed
docker exec api python /app/backend/scripts/inspect_issue.py --list --search "login" --include-processed

# Inspect issue without fetching S3 logs (faster)
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id> --no-logs

# Default output is a summary: long fields (description, device info, IndexedDB) are truncated
# and logs are filtered to errors/warnings only. Use --full-logs to see everything untruncated.
# Output can be very long — pipe to a file or use grep to filter.
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id> --full-logs
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id> --full-logs 2>&1 | grep -i "error\|warning\|keyword"

# Delete issue (after confirmed fixed; removes from Directus and S3). Use --yes to skip confirmation.
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id> --delete --yes

# Inspect a specific user by email
docker exec api python /app/backend/scripts/inspect_user.py <email_address>
```

---

## User Activity Timeline (Cross-Service Logs)

The `inspect_user_logs.py` script builds a unified, chronologically sorted timeline of all actions a specific user triggered across the entire system — API, task workers, app containers, upload/preview satellites, compliance logs, and client console logs (admin only).

```bash
# Basic usage — last 24h of activity for a user (by email)
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com

# By user ID
docker exec api python /app/backend/scripts/inspect_user_logs.py 550e8400-e29b-41d4-a716-446655440000

# Last 60 minutes only
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com --since 60

# Filter by category
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com --category auth,chat,error

# Filter by log level
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com --level warning

# Follow mode (poll every 5s, like tail -f)
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com --follow

# JSON output (for programmatic use)
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com --json

# Verbose mode (show raw log lines alongside parsed events)
docker exec api python /app/backend/scripts/inspect_user_logs.py someone@example.com --verbose
```

### How It Works

1. Resolves the user by email or UUID (queries Directus)
2. Runs parallel targeted Loki queries per service: `api-logs`, `compliance-logs`, `container-logs`, `client-console`
3. Fetches satellite logs from upload/preview servers via HTTP Admin Log API
4. Parses and classifies events using regex patterns into categories: `auth`, `chat`, `sync`, `embed`, `usage`, `settings`, `client`, `error`, `other`
5. Merges all events into a single chronological timeline
6. Displays with color-coded categories and log levels

### Options

| Flag             | Description                                            |
| ---------------- | ------------------------------------------------------ |
| `--since N`      | Minutes to look back (default: 1440 = 24h)             |
| `--category X,Y` | Filter by event categories                             |
| `--level X`      | Minimum log level: `debug`, `info`, `warning`, `error` |
| `--follow`       | Poll every 5s for new events (Ctrl+C to stop)          |
| `--json`         | JSON output                                            |
| `--verbose`      | Show raw log lines alongside parsed events             |
| `--prod`         | Query production via Admin Debug API (placeholder)     |

### Event Categories

| Category   | What it captures                                   |
| ---------- | -------------------------------------------------- |
| `auth`     | Login, logout, token refresh, session validation   |
| `chat`     | Message send/receive, AI dispatch, chat operations |
| `sync`     | Cache sync, Phase 1/2 operations                   |
| `embed`    | Embed creation, resolution, rendering              |
| `usage`    | Usage tracking, rate limits, quota checks          |
| `settings` | Preference changes, app store toggles              |
| `client`   | Browser console logs (admin users only)            |
| `error`    | Any ERROR/CRITICAL level log mentioning the user   |

---

## Newsletter Inspection

```bash
# Summary counts (confirmed, pending, ignored, language breakdown)
docker exec api python /app/backend/scripts/inspect_newsletter.py

# Show all subscribers with decrypted emails
docker exec api python /app/backend/scripts/inspect_newsletter.py --show-emails

# Show pending (unconfirmed) subscriptions from cache
docker exec api python /app/backend/scripts/inspect_newsletter.py --show-pending

# Show monthly subscription timeline
docker exec api python /app/backend/scripts/inspect_newsletter.py --timeline

# Show everything
docker exec api python /app/backend/scripts/inspect_newsletter.py --show-emails --show-pending --timeline

# JSON output
docker exec api python /app/backend/scripts/inspect_newsletter.py --json
```

---

## AI Request Debugging

The `inspect_last_requests.py` script provides flexible debugging of AI request processing with multiple viewing modes.

**IMPORTANT:** Only **admin user requests** are cached for debugging (72-hour retention). Regular user requests are never cached for privacy.

### Quick List View (Default)

```bash
# List all cached requests (quick overview)
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --list

# Filter by chat ID
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id <chat_id> --list

# Filter by task ID
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --task-id <task_id> --list

# Show only requests from last 5 minutes
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --since-minutes 5 --list

# Show only requests with errors
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --errors-only --list
```

### Detailed Summary View

```bash
# Show detailed summary with statistics
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --summary

# Combine filters for targeted analysis
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id <chat_id> --errors-only --summary
```

### Full YAML Export

```bash
# Save full debug data to YAML file
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --yaml

# With custom output path
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --yaml --output /tmp/debug.yml

# Copy to host machine
docker cp api:/app/backend/scripts/debug_output/last_requests_<timestamp>.yml ./debug_output.yml
```

### Other Options

```bash
# JSON output (for programmatic use)
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --json

# Clear all cached debug data
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --clear
```

### Filtering Options (combinable)

- `--chat-id <id>` - Filter by chat ID
- `--task-id <id>` - Filter by Celery task ID
- `--since-minutes <n>` - Only show requests from last N minutes
- `--errors-only` - Only show requests with detected errors

### Output Modes (mutually exclusive)

- `--list` - Concise table view (default)
- `--summary` - Detailed summary with statistics
- `--yaml` - Full YAML export to file
- `--json` - JSON output for scripts

---

## User Debugging

```bash
# Show user statistics
docker exec -it api python /app/backend/scripts/show_user_stats.py

# Show all chats for a specific user
docker exec -it api python /app/backend/scripts/show_user_chats.py <user_id>

# Show most recent user
docker exec -it api python /app/backend/scripts/show_last_user.py
```

---

## Cache Inspection (Dragonfly)

```bash
# Connect to Dragonfly cache CLI
docker exec -it cache redis-cli

# Common commands (inside redis-cli):
KEYS *sync:*    # List sync cache keys
KEYS *debug:*   # List debug entries
GET <key>       # Get value for a key
TTL <key>       # Check time-to-live
DBSIZE          # Total number of keys
```

---

## Celery Task Queue Inspection

```bash
docker exec -it task-worker celery -A backend.core.api.worker inspect active      # Active tasks
docker exec -it task-worker celery -A backend.core.api.worker inspect reserved    # Queued tasks
docker exec -it task-worker celery -A backend.core.api.worker inspect registered  # Registered types
docker exec -it task-worker celery -A backend.core.api.worker inspect scheduled   # Scheduled tasks
```

---

## Admin Debug API (Remote Debugging)

Remote debugging endpoints when SSH access is unavailable. Requires admin API key.

**IMPORTANT:** On the **dev server** (where we have SSH/docker access), always prefer the inspection scripts above over these API endpoints. The scripts provide richer output, decrypt all fields, and fetch S3 reports directly. Reserve the Admin Debug API for **production debugging** or when you don't have shell access.

**Base URLs:** `https://api.openmates.org` (prod) or `https://api.dev.openmates.org` (dev)

### Query Logs

```bash
# Get logs from specific services
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/logs?services=api,task-worker&lines=50&since_minutes=30"

# Search for errors
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/logs?search=ERROR&since_minutes=60"
```

**Allowed services:** `api`, `cms`, `cms-database`, `task-worker`, `task-scheduler`, `app-ai`, `app-web`, `app-videos`, `app-news`, `app-maps`, `app-code`, `app-images`, `app-ai-worker`, `app-web-worker`, `app-images-worker`, `cache`

### Inspect Data

```bash
# Inspect a chat
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/chat/<chat_id>"

# Inspect a user by email
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/user/<email>"

# Inspect an embed
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/embed/<embed_id>"

# Inspect last AI requests (filter by chat_id optional)
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/last-requests?chat_id=<chat_id>"
```

### Issue Reports

```bash
# List issues
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/issues?search=login&include_processed=true"

# Get issue with logs
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/issues/<issue_id>?include_logs=true"

# Delete issue
curl -X DELETE -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/issues/<issue_id>"
```

---

## Admin Debug CLI (Production Debugging)

CLI wrapper (`backend/scripts/admin_debug_cli.py`) for the Admin Debug API. **Use this to debug production** from the dev server via `docker exec api`.

**Setup:** Add `SECRET__ADMIN__DEBUG_CLI__API_KEY=sk-api-xxxxx` to `.env`, restart vault-setup, then confirm the new device in Settings > Developers > Devices on production.

**Commands:** `logs`, `upload-logs`, `preview-logs`, `issues`, `issue <id>`, `user <email>`, `chat <id>`, `embed <id>`, `requests`. Add `--dev` for dev server, `--json` for raw output.

```bash
# Core API server logs (via Loki)
docker exec api python /app/backend/scripts/admin_debug_cli.py logs --services api,task-worker --search "ERROR" --since 30

# Upload server logs (upload.openmates.org — separate VM, no Loki)
docker exec api python /app/backend/scripts/admin_debug_cli.py upload-logs
docker exec api python /app/backend/scripts/admin_debug_cli.py upload-logs --services app-uploads,clamav --since 30 --search "ERROR"

# Preview server logs (preview.openmates.org — separate VM, no Loki)
docker exec api python /app/backend/scripts/admin_debug_cli.py preview-logs
docker exec api python /app/backend/scripts/admin_debug_cli.py preview-logs --since 30 --search "WARNING|ERROR" --lines 200

# Other commands
docker exec api python /app/backend/scripts/admin_debug_cli.py user someone@example.com
docker exec api python /app/backend/scripts/admin_debug_cli.py issues
```

### Setup for upload-logs / preview-logs

The satellite log commands require additional API keys stored in the core Vault:

1. Generate two random keys:

   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"  # for upload
   python3 -c "import secrets; print(secrets.token_hex(32))"  # for preview
   ```

2. Add to core server `.env`:

   ```
   SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY=<upload-key>
   SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY=<preview-key>
   ```

3. Add to the **upload VM**'s `backend/upload/.env`:

   ```
   ADMIN_LOG_API_KEY=<upload-key>   # must match SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY
   ```

4. Add to the **preview VM**'s `.env` (root `.env` that docker-compose.preview.yml reads):

   ```
   ADMIN_LOG_API_KEY=<preview-key>  # must match SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY
   ```

5. Restart vault-setup on the core server to import the new keys:

   ```bash
   docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml restart vault-setup
   ```

6. Rebuild and restart the upload and preview containers on their VMs to pick up `ADMIN_LOG_API_KEY`.

**Note:** The upload and preview servers need the Docker socket mounted at `/var/run/docker.sock` inside their containers (plus `docker` CLI available) to run `docker compose logs`. See the next section for docker-compose additions.
