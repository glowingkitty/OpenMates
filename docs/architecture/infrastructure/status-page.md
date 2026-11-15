---
status: active
last_verified: 2026-11-14
key_files:
- deployment/status_server/gatus/config.yaml
- deployment/status_server/agent/status_agent/alerts.py
- scripts/status_server.py
- backend/status/main.py
- backend/core/api/app/routes/status_routes.py
- backend/core/api/app/services/status_aggregator.py
- backend/core/api/app/services/test_results_service.py
claims:
- id: arch-infrastructure-status-page-behavior
  type: unit
  claim: Status Page is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - backend/status/main.py
  - backend/core/api/app/routes/status_routes.py
  - backend/core/api/app/services/status_aggregator.py
  - backend/core/api/app/services/test_results_service.py
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-infrastructure-status-page-behavior
  verified: '2026-06-11'
- id: arch-infrastructure-status-page-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-status-page-source-1
  anchors:
  - type: file_exists
    path: backend/core/api/app/routes/status_routes.py
- id: arch-infrastructure-status-page-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-status-page-source-2
  anchors:
  - type: file_exists
    path: backend/core/api/app/services/status_aggregator.py
- id: arch-infrastructure-status-page-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-status-page-source-3
  anchors:
  - type: file_exists
    path: backend/core/api/app/services/test_results_service.py
---

# Status Page

> `status.openmates.org` is an external monitor on one small VPS (netcup, Nuremberg). It runs Gatus checks and a small status agent, and publishes a static public page. The web app's own `/status` route (V2 below) is separate.

## Why This Exists

All production AI chats were down on 13 Nov 2026 from 16:58 UTC and nobody was alerted. Production's own `/v1/health` stayed "healthy" from a stale cache. Monitoring that runs inside the monitored servers cannot report that they are down. So the monitor lives outside our infrastructure, uses real chat requests, and alerts by Discord and email.

## How It Works

### External status server (`deployment/status_server/`)

Contract: `specifications/architecture/external-status-monitoring`. Runbook: `deployment/status_server/README.md`.

- **Gatus** (`gatus/config.yaml`) runs the free HTTP checks every minute: web app, app shell, API, AI-worker liveness (`GET /v1/health/liveness`), uploads and link previews. Every 5 minutes it reads providers' official Statuspage feeds. It stores the results in SQLite. Its own alerting is off, and its UI is reachable only through an SSH tunnel.
- **Status agent** (`agent/status_agent/`, stdlib Python) runs the paid probes and pushes them to Gatus external endpoints:
  - every 5 minutes, a real Gemini Flash Lite chat without an account, using the `X-OpenMates-Monitor-Token` header;
  - every 5 minutes, the same chat with an account, using the monitoring account's API key;
  - every 30 minutes, a web-search skill;
  - every 5 minutes, the Google Cloud incident feed.
  
  The agent also reads production `/v1/health` each minute, for alerts only. Then it:
  - applies the escalation policy (`alerts.py`): 2 failures confirm an outage; reminders follow at 15 min, at 1 h, then every 3 h; one resolved message when it recovers; state is persisted;
  - sends alerts to Discord, with Brevo email as backup;
  - writes `status.json` for the page (components, providers, 90 daily bars, incidents).
- **Caddy** serves the static page (`site/`) and `/data/status.json`. It handles TLS and keeps no access log.
- **Monitor traffic** is never billed. It does not use the free anonymous allowance and is left out of usage entries and growth metrics (`backend/shared/python_utils/monitor_traffic.py`).
- **Delegated alerts.** With `OPENMATES_HEALTH_ALERTS_DELEGATED=true`, the backend still records health transitions but stops posting them. The external monitor alerts for them instead, with repeats and a resolved message.
- **Dev-server cross-check.** `scripts/status_server.py watch` runs on a 5-minute user timer (`scripts/status-server-watch-setup.sh`). It alerts when the page is unreachable or `status.json` is older than 10 minutes.

### Legacy independent service (`backend/status/`)

An earlier FastAPI + SQLite + Svelte status service that was never deployed. The external status server above replaces it. Its old behavior: direct HTTP checks of the web app, API, upload and preview endpoints, provider status read from `/v1/health`, and environment views at `/` and `/dev`.

### V2 Status Page (Main Web App)

The `/status` route on the main web app was redesigned into three sections:

**1. Services** -- flat list of infrastructure dependencies (Vercel, API Server, Sightengine, Brevo), each with status dot and 30-day timeline.

**2. Apps** -- expandable per-app (AI, Web, etc.). On expand: providers with individual timelines + skills with overall status. Data loaded lazily via `GET /v1/status/apps?app=<id>`.

**3. Functionalities** -- maps Playwright test categories to user-facing features (Signup, Login, Chat, Payment, Search & AI, etc.). Each shows pass rate and 30-day timeline. On expand: sub-category timelines and individual tests. Data loaded lazily via `GET /v1/status/functionalities?name=<name>`. Mapping defined in `FUNCTIONALITY_MAP` in `status_aggregator.py`.

### API Endpoints

| Endpoint                                    | Purpose                                          |
|---------------------------------------------|--------------------------------------------------|
| `GET /v1/status`                            | Full initial payload: services, apps, functionalities, issues, timeline |
| `GET /v1/status/apps?app=<id>`              | App detail: providers + skills                   |
| `GET /v1/status/functionalities?name=<name>`| Functionality detail: sub-categories + tests     |
| `GET /v1/status/timeline/intraday?date=<d>` | Hourly intra-day breakdown for any timeline      |
| `GET /v1/status/incidents`                  | Incident history                                 |

### Timelines

- All timelines support click to show date/time/status details.
- Days with multiple runs show a 24-hour hourly sub-timeline.
- Height configurable via `height` prop (default 1.1rem).

### Caching

- Root-level data (services, app summaries, functionality summaries) pre-cached in Redis with 60s TTL.
- Detail data (providers, skills, tests) loaded on demand with 60s in-memory cache.

## Edge Cases

- If a core API is unreachable, provider status is marked `unknown` on the independent status service.
- Health events from `health_check_tasks.py` feed the 30-day timelines; data cleaned up after 90 days.

## Related Docs

- [Health Checks](./health-checks.md) -- source of provider/app/service health data
- Frontend components: `InfraServices.svelte`, `AppGroup.svelte`, `FunctionalityGroup.svelte`, `TimelineBar.svelte`
