---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/docker-compose.yml
  - backend/preview/docker-compose.preview.yml
  - deployment/dev_server/Caddyfile
---

# Server Architecture

> Docker Compose stack with a core API, Directus CMS, per-app API containers, Celery workers, and a separate preview server for image/metadata proxying.

## Why This Exists

- Each app gets its own container pair (API + worker) for independent scaling and fault isolation
- Infrastructure services (cache, vault, monitoring) are co-located in the same Compose stack
- The preview server runs on a separate VM for security isolation (blocks SSRF, prevents hotlinking)

## How It Works

### Core Services

Defined in [docker-compose.yml](../../backend/core/docker-compose.yml):

| Container | Image / Build | Purpose |
|-----------|--------------|---------|
| `api` | Custom (FastAPI) | Core REST API, WebSocket server |
| `task-worker` | Custom (Celery) | Background tasks (email, deletion, cache warming) |
| `task-scheduler` | Custom (Celery Beat) | Scheduled/periodic task dispatch |
| `cms` | `directus/directus:11.5` | Directus CMS for data management |
| `cms-database` | `postgres:13-alpine` | PostgreSQL database |
| `cms-setup` | Custom | Schema migration on startup (runs once) |
| `cache` | `dragonflydb/dragonfly` | Redis-compatible cache (Dragonfly) |
| `vault` | `hashicorp/vault:1.19` | Secret management, transit encryption |
| `vault-setup` | Custom | Vault initialization (runs once) |
| `core-admin-sidecar` | Custom | Admin utilities (health checks, scripts) |

### App Containers (Two-Container Pattern)

Each app follows API + Worker separation:

| App | API Container | Worker Container |
|-----|--------------|-----------------|
| AI | `app-ai` | `app-ai-worker` |
| Web | `app-web` | -- |
| Videos | `app-videos` | -- |
| Audio | `app-audio` | -- |
| News | `app-news` | -- |
| Events | `app-events` | -- |
| Maps | `app-maps` | -- |
| Travel | `app-travel` | -- |
| Health | `app-health` | -- |
| Shopping | `app-shopping` | -- |
| Code | `app-code` | -- |
| Docs | `app-docs` | -- |
| Mail | `app-mail` | -- |
| Images | `app-images` | `app-images-worker` |
| PDF | `app-pdf` | `app-pdf-worker` |
| Reminder | `app-reminder` | -- |
| Jobs | `app-jobs` | -- |
| Math | `app-math` | -- |

Currently only AI, Images, and PDF have dedicated worker containers. Other apps handle tasks via the core `task-worker` or process synchronously.

Each API container exposes internal FastAPI endpoints on the Docker network (e.g., `/skill/ask`). Service discovery is automatic via Docker networking.

### Monitoring Stack

| Container | Image | Purpose |
|-----------|-------|---------|
| `openobserve` | `zinclabs/openobserve:v0.70.0-rc3` | Log aggregation, metrics (replaces Loki+Grafana) |
| `prometheus` | `prom/prometheus:v3.2.1` | Metrics collection |
| `alertmanager` | `prom/alertmanager:v0.31.1` | Alert routing |
| `cadvisor` | `cadvisor:v0.47.2` | Container resource metrics |
| `promtail` | `grafana/promtail:3.4.2` | Log shipping to OpenObserve |

Grafana and a backup-service are defined but commented out.

### Preview Server

Runs on a separate VM at `preview.openmates.org`. See [docker-compose.preview.yml](../../backend/preview/docker-compose.preview.yml).

**Endpoints:**
- `GET /api/v1/image` -- fetch, resize, cache external images (disk-based LRU, 10GB, 7-day TTL)
- `GET /api/v1/favicon` -- fetch and cache favicons (tries `/favicon.ico`, falls back to Google Favicon Service)
- `POST /api/v1/metadata` -- extract Open Graph / HTML metadata (24-hour cache TTL)
- `GET /health`, `GET /health/detailed` -- health checks

**Security:** referer validation, SSRF protection (blocks private IPs), content-type validation, optional API key auth. 4 uvicorn workers by default.

**Self-hosted option:** uncomment the preview service in the core `docker-compose.yml`.

## Edge Cases

- **Docker network isolation:** app containers communicate via internal network only; not exposed publicly
- **Vault token management:** `vault-setup` runs once on startup; `api` and `task-worker` wait for it via `depends_on: service_completed_successfully`
- **Cache as Dragonfly:** drop-in Redis replacement with better memory efficiency; same protocol

<!-- VERIFY: whether all app containers without dedicated workers actually use core task-worker vs synchronous processing -->

## Related Docs

- [Security Architecture](./security.md) -- Vault integration, encryption
- [Apps Architecture](../apps/) -- app skill execution model
