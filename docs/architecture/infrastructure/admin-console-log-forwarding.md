---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/services/clientLogForwarder.ts
  - frontend/packages/ui/src/services/logCollector.ts
  - backend/core/api/app/routes/admin_client_logs.py
  - backend/core/api/app/services/openobserve_push_service.py
---

# Admin Console Log Forwarding

> Browser console logs from admin users are forwarded in real-time to OpenObserve via a backend proxy, providing unified client+server observability.

## Why This Exists

Debugging client-side issues requires seeing browser logs alongside server logs. Admin-only forwarding keeps the feature scoped (no regular user data leaves the browser) while providing a unified timeline in OpenObserve.

## How It Works

### Architecture

```
Browser (admin only)
  logCollector.ts       -- patches console.{log,info,warn,error,debug}
  clientLogForwarder.ts -- batches every 5s, durable IndexedDB queue
      | POST /v1/admin/client-logs (credentials: include, keepalive: true)
  FastAPI (admin_client_logs.py)
      | Loki-compat push (aiohttp)
  OpenObserve :5080 (stream: "client-console", job="client-console")
```

### Forwarder Lifecycle

| Event                              | Action                                     |
|------------------------------------|--------------------------------------------|
| Login with `is_admin: true`        | `clientLogForwarder.start()`               |
| Session restore with `is_admin`    | `clientLogForwarder.start()`               |
| Logout                             | `clientLogForwarder.stop()` (drains first) |
| Session expiry                     | `clientLogForwarder.stop()`                |

The `is_admin` flag comes from `/v1/auth/login` and `/v1/auth/session` responses, sourced from the Redis user profile cache. When admin status changes via `AdminMethods.make_user_admin()` / `revoke_admin_privileges()`, the cache key is deleted immediately.

### Batching

- Flush interval: 5 seconds
- Max batch size: 50 entries
- Max batches per flush cycle: 25
- Durable IndexedDB queue (`om-admin-log-queue`) survives page refreshes

### Privacy

- Non-admin users: forwarder never starts. Logs stay in `logCollector` circular buffers; only sent on explicit issue submission.
- Messages sanitized client-side: API keys (`sk-api-*`), bearer tokens, and common sensitive fields redacted.
- OpenObserve endpoint never exposed to browser -- all pushes go through the backend proxy.

### Querying in OpenObserve

```sql
SELECT _timestamp, user_email, level, message
FROM "client-console"
WHERE _timestamp > NOW() - INTERVAL '1 hour'
ORDER BY _timestamp DESC
```

Stream labels: `job="client-console"`, `level`, `user_email`, `server_env`, `source="browser"`.

### Environment Variables

| Variable                  | Where   | Purpose                          |
|---------------------------|---------|----------------------------------|
| `OPENOBSERVE_ROOT_EMAIL`  | Backend | Basic auth for server-side push  |
| `OPENOBSERVE_ROOT_PASSWORD`| Backend | Basic auth for server-side push |

## Edge Cases

- If IndexedDB is unavailable (e.g., private browsing), falls back to a volatile in-memory queue.
- Backend proxy failure: entries remain in IndexedDB queue and are retried on next flush cycle.

## Related Docs

- [Logging System](./logging.md) -- server-side logging architecture
- Server logs reach OpenObserve via Promtail (Docker socket + file discovery)
