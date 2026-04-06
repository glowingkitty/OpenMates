---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/docker-compose.yml
  - backend/preview/docker-compose.preview.yml
  - deployment/dev_server/Caddyfile
---

# Server Architecture

> Docker Compose stack with a single FastAPI gateway hosting all app skills in-process, dedicated Celery workers for queue-driven workloads, Directus CMS, and a separate preview server for image/metadata proxying.

## Why This Exists

- One `api` container hosts all app skills in-process (OPE-342) — every `backend/apps/{name}/` folder is loaded via `importlib` at startup, no per-app containers
- Celery workers (`app-ai-worker`, `app-images-worker`, `app-pdf-worker`, `task-worker`, `task-scheduler`) run their own queues for long-running, parallelizable, or autoscaled work — they earn their RAM
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

### App Containers (Workers Only — In-Process Skills since OPE-342)

There are **no per-app sync API containers**. The 20 `app-{name}` Uvicorn containers that used to host one skill class each were removed in OPE-342: they burned ~2.6 GiB of idle RAM, added ~10 ms per skill call (HTTP serialization), required a 60-line `docker-compose.yml` entry per new app, and provided none of their claimed scaling/isolation benefits.

The `api` container now loads every `backend/apps/{name}/app.yml` via filesystem scan at startup and resolves each skill `class_path` via `importlib`. Skills are dispatched in-process via the `SkillRegistry` (`backend/core/api/app/services/skill_registry.py`) — see [app-skills.md](../apps/app-skills.md).

Only the Celery worker containers remain — they have real, queue-driven workloads:

| Worker | Queues | Why containerized |
|--------|--------|-------------------|
| `app-ai-worker` | `app_ai` | LLM streaming pipeline, distinct memory profile |
| `app-images-worker` | `app_images` | GPU/CPU-heavy image generation |
| `app-pdf-worker` | `app_pdf` | PDF rendering with `pymupdf`/`reportlab` |
| `task-worker` | `email`, `persistence`, `user_init`, … | Infrastructure tasks |
| `task-scheduler` | (Celery beat) | Periodic task dispatch |

Workers also build their own `SkillRegistry` instance in `init_worker_process()` so they can dispatch skills without HTTPing back to `api`.

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
