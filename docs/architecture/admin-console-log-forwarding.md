# Observability — OpenObserve RUM & Log Forwarding

> **Status**: Implemented
> **Last Updated**: 2026-03-09

## Overview

All client-side observability flows through the **OpenObserve browser SDK** (`@openobserve/browser-rum` + `@openobserve/browser-logs`). This replaced the former admin-only Loki log forwarder, giving us real observability for all users (not just admins) with zero backend proxy overhead.

## Architecture

### Browser → OpenObserve (direct, all users)

```
Browser SDK (openobserveRum.ts)
  └── @openobserve/browser-rum    → RUM events, JS errors, session replay
  └── @openobserve/browser-logs   → console.error / console.warn forwarding
        ↓  (direct HTTP from browser)
  OpenObserve :5080  (stream: "rum")
```

### Server logs → OpenObserve (via Promtail + Loki-compat push)

```
Docker containers → Promtail (file + Docker socket discovery)
                         ↓  (Loki-compat push)
                    OpenObserve :5080  (streams: "default", "api-logs", "compliance-logs")
```

### Admin browser logs → OpenObserve (optional legacy path)

The `/v1/admin/client-logs` route still exists for backward compatibility. It now calls `openobserve_push_service.py` which pushes to the OpenObserve Loki-compat endpoint. In practice, the browser SDK supersedes this for all new deployments.

## Key Files

| File | Purpose |
|------|---------|
| `frontend/packages/ui/src/services/openobserveRum.ts` | Browser SDK singleton — init, setUser, clearUser |
| `frontend/packages/ui/src/app.ts` | Calls `openobserveRumService.init()` at app start |
| `frontend/packages/ui/src/stores/authSessionActions.ts` | Calls `setUser()` on session restore, `clearUser()` on expiry |
| `frontend/packages/ui/src/stores/authLoginLogoutActions.ts` | Calls `setUser()` on login, `clearUser()` on logout |
| `backend/core/api/app/services/openobserve_push_service.py` | Server-side push to OpenObserve Loki-compat endpoint |
| `backend/core/api/app/services/openobserve_log_collector.py` | Server-side log queries via OpenObserve SQL API |
| `backend/core/api/app/routes/admin_client_logs.py` | Legacy admin log ingestion endpoint |

## Environment Variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `PUBLIC_OPENOBSERVE_RUM_ENDPOINT` | Frontend `.env` | Browser SDK endpoint (e.g. `https://openobserve.your-domain.com`) |
| `OPENOBSERVE_ROOT_EMAIL` | Backend docker-compose env | Basic auth for server-side queries/push |
| `OPENOBSERVE_ROOT_PASSWORD` | Backend docker-compose env | Basic auth for server-side queries/push |

## Privacy

- `setUser()` is called only after successful authentication — no identity before login
- `clearUser()` is called on logout — session is anonymized after sign-out
- No PII is captured by default; `defaultPrivacyLevel: "mask-user-input"` masks all form fields
- Session replay is opt-in (call `startRecording()` only with explicit user consent)
