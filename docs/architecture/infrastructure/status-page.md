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
