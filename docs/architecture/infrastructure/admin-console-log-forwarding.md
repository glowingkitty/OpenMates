# Observability — Client Log Forwarding to OpenObserve

> **Status**: Implemented
> **Last Updated**: 2026-03-10

## Overview

Browser console logs from **admin users** are forwarded in real-time to OpenObserve via a
backend proxy. This gives admins a unified view of client-side and server-side logs for
debugging without exposing the internal OpenObserve endpoint to regular users.

Non-admin users: the forwarder is never started. Their logs stay local (in the
`logCollector` circular buffers) and are only sent to the server on explicit issue
submission (`/v1/settings/issue-logs`).

## Architecture

### Admin browser logs to OpenObserve (via backend proxy)

```
Browser (admin only)
  logCollector.ts         -- patches console.{log,info,warn,error,debug}
  clientLogForwarder.ts   -- batches logs every 5s, durable IndexedDB queue
        |  POST /v1/admin/client-logs  (credentials: include, keepalive: true)
  FastAPI (admin_client_logs.py)
        |  Loki-compat push (aiohttp)
  OpenObserve :5080  (stream: "client-console", job="client-console")
```

### Server logs to OpenObserve (via Promtail)

```
Docker containers -> Promtail (file + Docker socket discovery)
                          |  (Loki-compat push)
                     OpenObserve :5080  (streams: "default", "api-logs", "compliance-logs")
```

## When the forwarder starts / stops

| Event | Action |
|-------|--------|
| Login with `is_admin: true` | `clientLogForwarder.start()` |
| Session restore with `is_admin: true` | `clientLogForwarder.start()` |
| Logout | `clientLogForwarder.stop()` (drains buffer first) |
| Session expiry | `clientLogForwarder.stop()` |

The `is_admin` flag comes from the `/v1/auth/login` and `/v1/auth/session` responses.
It is sourced from the Redis user profile cache (`user_profile:{user_id}`), populated
from Directus on first access. When admin status is granted or revoked via
`AdminMethods.make_user_admin()` / `revoke_admin_privileges()`, the cache key is
deleted immediately so the next session check fetches a fresh profile.

## Key Files

| File | Purpose |
|------|---------|
| `frontend/packages/ui/src/services/logCollector.ts` | Patches `console.*`, maintains circular buffers, notifies listeners |
| `frontend/packages/ui/src/services/clientLogForwarder.ts` | Batches logs every 5s, durable IndexedDB queue, POSTs to backend |
| `frontend/packages/ui/src/stores/authLoginLogoutActions.ts` | Calls `start()` on admin login, `stop()` on logout |
| `frontend/packages/ui/src/stores/authSessionActions.ts` | Calls `start()` on admin session restore, `stop()` on expiry |
| `backend/core/api/app/routes/admin_client_logs.py` | Receives batches, validates admin, proxies to OpenObserve |
| `backend/core/api/app/services/openobserve_push_service.py` | Loki-compat push to OpenObserve |
| `backend/core/api/app/services/directus/admin_methods.py` | Grants/revokes admin; invalidates Redis cache on change |

## Environment Variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `OPENOBSERVE_ROOT_EMAIL` | Backend docker-compose env | Basic auth for server-side push |
| `OPENOBSERVE_ROOT_PASSWORD` | Backend docker-compose env | Basic auth for server-side push |

## Querying logs in OpenObserve

```sql
-- All admin browser logs (last 1 hour)
SELECT _timestamp, user_email, level, message
FROM "client-console"
WHERE _timestamp > NOW() - INTERVAL '1 hour'
ORDER BY _timestamp DESC
```

Stream labels: `job="client-console"`, `level`, `user_email` (username), `server_env`, `source="browser"`.

## Privacy

- Forwarder only starts after successful admin authentication -- no logs before login
- Forwarder stops on logout -- no logs after sign-out
- Messages are sanitized on the client before queuing: API keys (`sk-api-*`), bearer
  tokens, and common sensitive fields (`password`, `token`, `key`, `auth`) are redacted
- Only admin users logs are forwarded; regular users logs never leave the browser
  (except on explicit issue submission)
- The OpenObserve endpoint is never exposed to the browser -- all pushes go through
  the backend proxy, so the internal URL stays internal
