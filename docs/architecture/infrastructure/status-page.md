---
status: active
last_verified: 2026-03-24
key_files:
  - backend/status/main.py
  - backend/core/api/app/routes/status_routes.py
  - backend/core/api/app/services/status_aggregator.py
  - backend/core/api/app/services/test_results_service.py
---

# Status Page

> Independent status service (`status.openmates.org`) with a V2 redesign surfacing services, apps, and Playwright-backed functionality health on the main web app.

## Why This Exists

Users and operators need a public status page that stays available even when core services are degraded. The independent service on a separate VM provides this guarantee.

## How It Works

### Independent Status Service (`backend/status/`)

- FastAPI + SQLite, deployed on a dedicated VM.
- Svelte SPA (Vite build) served by the same FastAPI process.
- Direct HTTP checks for web app, core API, upload, and preview endpoints.
- Provider/external-service status read from each core API environment's `/v1/health` (avoids duplicating provider API calls).
- Environment views: `/` = production, `/dev` = development.

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
