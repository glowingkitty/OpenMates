# Admin Console Log Forwarding

> **Status**: Implemented
> **Last Updated**: 2026-02-12

## Overview

Admin Console Log Forwarding automatically captures browser console logs from **admin users only** and pushes them to Loki for centralized storage and querying via Grafana. This provides a unified view of both client-side and server-side logs, making it significantly easier to debug issues without requiring manual "Report Issue" submissions.

## User Privacy

**Regular users are never affected by this feature.** Console log forwarding is strictly limited to admin users through multiple layers of enforcement:

| Layer                 | Enforcement                                                                                                                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Frontend (client)** | `ClientLogForwarder` only starts when `is_admin === true` in the user profile. It is never instantiated or activated for non-admin users.                                                   |
| **Backend (server)**  | The `POST /v1/admin/client-logs` endpoint requires the `require_admin` dependency, which verifies admin status via Directus before accepting any logs. Non-admin requests receive HTTP 403. |
| **Auth flow**         | The forwarder starts on login/session restore only if `data.user.is_admin` is true, and stops immediately on logout or session expiry.                                                      |

No browsing data, console output, or telemetry of any kind is ever collected from regular users through this mechanism. The existing `logCollector` service (used for issue reports) continues to work locally in the browser for all users, but its data is only sent to the server when a user explicitly clicks "Report Issue."

## Architecture

```
Browser (Admin user)
  |
  logCollector.ts (existing singleton)
  |  Intercepts console.log/info/warn/error/debug
  |  Maintains circular buffer of 100 entries
  |  Sanitizes sensitive data (API keys, tokens, passwords)
  |
  +-- onNewLog() callback
  |
  ClientLogForwarder (new service)
  |  Buffers entries (max 200 in memory)
  |  Flushes every 5 seconds or at 50 entries
  |  Generates unique tab ID per browser tab
  |
  POST /v1/admin/client-logs
  |  Auth: cookie session + admin check
  |  Rate limit: 10 requests/minute
  |  Max 50 entries per batch
  |
  LokiPushService (new service)
  |  Formats entries into Loki push API format
  |  Groups by log level into separate streams
  |
  Loki (POST /loki/api/v1/push)
  |  Labels: job="client-console", level, user (username), server_env, source="browser"
  |  Retention: 7 days (inherited from existing Loki config)
  |
  Grafana
     Query: {job="client-console"}
```

## Key Files

### Frontend

| File                                                                                                                        | Purpose                                                                     |
| --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [`frontend/packages/ui/src/services/logCollector.ts`](../frontend/packages/ui/src/services/logCollector.ts)                 | Console interceptor with listener callback support (`onNewLog`/`offNewLog`) |
| [`frontend/packages/ui/src/services/clientLogForwarder.ts`](../frontend/packages/ui/src/services/clientLogForwarder.ts)     | Batches and forwards logs to backend; manages lifecycle (start/stop)        |
| [`frontend/packages/ui/src/stores/authLoginLogoutActions.ts`](../frontend/packages/ui/src/stores/authLoginLogoutActions.ts) | Starts forwarder on login (if admin), stops on logout                       |
| [`frontend/packages/ui/src/stores/authSessionActions.ts`](../frontend/packages/ui/src/stores/authSessionActions.ts)         | Starts forwarder on session restore (if admin), stops on session expiry     |
| [`frontend/packages/ui/src/config/api.ts`](../frontend/packages/ui/src/config/api.ts)                                       | API endpoint definition (`apiEndpoints.admin.clientLogs`)                   |

### Backend

| File                                                                                                          | Purpose                                                  |
| ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| [`backend/core/api/app/routes/admin_client_logs.py`](../backend/core/api/app/routes/admin_client_logs.py)     | POST endpoint receiving batched client logs (admin-only) |
| [`backend/core/api/app/services/loki_push_service.py`](../backend/core/api/app/services/loki_push_service.py) | Pushes formatted log entries to Loki's HTTP push API     |
| [`backend/core/api/main.py`](../backend/core/api/main.py)                                                     | Router registration                                      |

## Loki Labels

All client console logs are stored in Loki with these labels:

| Label        | Value                            | Purpose                                             |
| ------------ | -------------------------------- | --------------------------------------------------- |
| `job`        | `client-console`                 | Distinguishes from server-side container logs       |
| `level`      | `info`, `warn`, `error`, `debug` | Log level (note: `console.log` is mapped to `info`) |
| `user_email` | Admin username                   | Identifies which admin generated the logs           |
| `server_env` | `development` or `production`    | Server environment                                  |
| `source`     | `browser`                        | Indicates client-side origin                        |

Each log message is also prefixed with the browser tab ID and current page URL for context:

```
[tab=a1b2c3d4] [/chat/abc123] TypeError: Cannot read property 'x' of undefined
```

## Querying in Grafana

### Common LogQL Queries

```logql
# All admin client console logs
{job="client-console"}

# Only errors from client
{job="client-console", level="error"}

# Specific admin's logs
{job="client-console", user_email="adminuser"}

# Client errors from last 30 minutes
{job="client-console", level="error"} | line_format "{{.message}}"

# Correlate client + server logs in the same time window
# (run these as two separate queries in Grafana's Explore view)
{job="client-console", level="error"}
{service="api"} |= "ERROR"

# Filter by specific page
{job="client-console"} |= "/chat/"

# Filter by specific tab
{job="client-console"} |= "tab=a1b2c3d4"
```

### Grafana Setup

Client console logs are automatically available in Grafana (accessible via SSH tunnel on port 3000) through the existing Loki datasource. No additional Grafana configuration is needed.

To view the logs:

1. Open Grafana > Explore
2. Select the "Loki" datasource
3. Use the query `{job="client-console"}`
4. Optionally filter by level, user, or search for specific text

## Rate Limiting and Volume Control

| Control               | Value                                    | Purpose                                         |
| --------------------- | ---------------------------------------- | ----------------------------------------------- |
| Client flush interval | 5 seconds                                | Batches logs to reduce HTTP requests            |
| Max batch size        | 50 entries                               | Caps entries per request                        |
| Max buffer size       | 200 entries                              | Prevents unbounded memory growth during bursts  |
| Server rate limit     | 10 requests/minute                       | Prevents abuse; ~500 entries/min max throughput |
| Message truncation    | 2000 chars (server), 1000 chars (client) | Limits individual log entry size                |
| Loki retention        | 7 days                                   | Inherited from existing Loki config             |

**Worst-case throughput**: 50 entries x 2000 chars x 10 req/min = ~1 MB/min. In practice, admin usage generates far less than this.

## Data Sanitization

Log messages are sanitized by the existing `logCollector` on the client side before forwarding. The following patterns are automatically redacted:

| Pattern                 | Replacement            |
| ----------------------- | ---------------------- |
| API keys (`sk-api-...`) | `[API-KEY-REDACTED]`   |
| Bearer tokens           | `[TOKEN-REDACTED]`     |
| Password fields         | `password: [REDACTED]` |
| Token fields            | `token: [REDACTED]`    |
| Key fields              | `key: [REDACTED]`      |
| Auth fields             | `auth: [REDACTED]`     |

Object arguments with sensitive keys (`password`, `token`, `apiKey`, `authorization`, `bearer`) are also redacted before forwarding.

## Lifecycle

1. **Login**: After successful authentication, if `data.user.is_admin === true`, `clientLogForwarder.start()` is called
2. **Session restore**: On page refresh, if the session check returns `is_admin === true`, the forwarder starts
3. **Active**: Logs are batched and sent every 5 seconds (or when 50 entries accumulate)
4. **Auth failure**: If the backend returns 401/403, the forwarder auto-stops
5. **Logout**: `clientLogForwarder.stop()` is called, remaining logs are flushed
6. **Session expiry**: Forwarder is stopped before session cleanup

The forwarder is idempotent - calling `start()` multiple times has no effect if already running.

## Read Next

- [Server Inspection Scripts](../CLAUDE.md#server-inspection-scripts) - Direct server debugging tools
- [Debugging Backend Issues](../CLAUDE.md#debugging-backend-issues) - Docker log commands
- [Admin Debug CLI](../CLAUDE.md#admin-debug-cli-production-debugging) - Remote production debugging
