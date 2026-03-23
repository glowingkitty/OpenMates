# Status Page Architecture

## Context

OpenMates needs a public status page (`status.openmates.org`) that remains available even when development or production core services are restarting or degraded.

Required visibility includes:

- Web app, core API, upload server, and preview server availability
- Incident history and downtime trends
- Response time trends over time
- Uptime percentages for monitored services
- Provider/service status used by OpenMates apps (AI providers, payment, email, moderation)
- A `/dev` view that uses the development core API while keeping upload/preview shared

## Decision

Implement an **independent status service** under `backend/status/` and deploy it on a dedicated VM.

- Backend: FastAPI + SQLite
- Frontend: Svelte SPA (Vite build) served by the same FastAPI service
- Health source:
  - Direct checks for web app/core API/upload/preview endpoints
  - Provider/external-service status read from each core API environment's `/v1/health`
- Separate environment views:
  - `/` = production environment
  - `/dev` = development environment

## Why

- Independence: status service does not run on core dev/prod VMs
- Operational clarity: one place to compare prod vs dev behavior
- Cost control: no duplicate provider API test calls from the status VM
- Simple ops: single process service with local SQLite persistence

## Alternatives Rejected

1. **Status route inside existing web app (Vercel)**
   - Rejected because status availability would be tied to the same frontend deployment path and runtime dependencies.

2. **Status data served only from core API `/v1/health`**
   - Rejected because status visibility should remain available when core API is unreachable.

3. **Independent provider API checks from status VM**
   - Rejected because it duplicates secrets, increases maintenance overhead, and introduces unnecessary provider API costs.

## Consequences

- New deployable service to maintain (`backend/status`)
- Status VM requires endpoint URL configuration for prod/dev/upload/preview
- Provider status is marked `unknown` if a core API is unavailable

## V2 Status Page Redesign (2026-03)

The `/status` route on the main web app was redesigned from 8 overlapping service groups + 3 test suites into three clear sections:

### Sections

1. **Services** — flat list of 4 infrastructure dependencies (Vercel, API Server, Sightengine, Brevo), each with status dot and 30-day timeline
2. **Apps** — expandable per-app (AI, Web, etc.). On expand: shows providers with individual timelines + skills with overall status. Data loads lazily via `GET /v1/status/apps?app=<id>`
3. **Functionalities** — maps Playwright test categories to user-facing features (Signup, Login, Chat, Payment, etc.). Each shows pass rate and 30-day timeline. On expand: sub-category timelines (e.g., Chat Flow, Chat Search), then individual tests. Data loads lazily via `GET /v1/status/functionalities?name=<name>`

### Key API endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/status` | Full initial payload: services, apps, functionalities, issues, timeline |
| `GET /v1/status/apps?app=<id>` | App detail: providers + skills |
| `GET /v1/status/functionalities?name=<name>` | Functionality detail: sub-categories + tests |
| `GET /v1/status/timeline/intraday?date=<date>` | Hourly-grouped intra-day data for any timeline |
| `GET /v1/status/incidents` | Incident history (retained from v1) |

### Timeline enhancements

- All timelines support click to show date/time/status details
- Days with multiple runs show an hourly 24-hour sub-timeline (24 segments)
- Hours with multiple runs show aggregated summaries
- Timeline height is now configurable via a `height` prop (default 1.1rem)

### Caching

- Root-level data (services, apps summaries, functionality summaries) pre-cached in Redis with 60s TTL
- Detail data (providers, skills, tests) loaded on demand with 60s in-memory cache

### Files

- Backend: `status_aggregator.py`, `test_results_service.py`, `status_routes.py`, `health_check_tasks.py`
- Frontend: `+page.svelte`, `InfraServices.svelte`, `AppGroup.svelte`, `FunctionalityGroup.svelte`, `ExpandableIssues.svelte`, `TimelineBar.svelte`
- Functionality mapping: `FUNCTIONALITY_MAP` in `status_aggregator.py`
