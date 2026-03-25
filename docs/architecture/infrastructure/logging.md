---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/utils/setup_logging.py
  - backend/core/api/app/utils/setup_compliance_logging.py
  - backend/core/api/app/utils/log_filters.py
---

# Logging System

> JSON-structured logging with automatic sensitive data redaction, size-based rotation for application logs, and time-based rotation for two compliance log streams.

## Why This Exists

All backend services need consistent, machine-parseable logs for debugging and monitoring. Compliance logs (audit + financial) must be retained for legal requirements (GDPR and AO SS 147) with no accidental deletion, while application logs rotate to prevent disk exhaustion.

## How It Works

### Framework

- Python `logging` module with `pythonjsonlogger.jsonlogger.JsonFormatter`
- Configuration via `logging.config.dictConfig()` in `setup_logging.py`
- Compliance handlers added programmatically by `setup_compliance_logging.py` at startup

### Log Files

| File                        | Handler Type              | Rotation                        | Retention            |
|-----------------------------|---------------------------|---------------------------------|----------------------|
| `api.log`                   | `RotatingFileHandler`     | Size-based (10 MB default)      | 5 backups (~50 MB)   |
| `audit-compliance.log`      | `TimedRotatingFileHandler`| Time-based (daily default)      | Unlimited (manual)   |
| `financial-compliance.log`  | `TimedRotatingFileHandler`| Time-based (daily default)      | Unlimited (manual)   |

Log directory resolution: `LOG_DIR` env var > `/app/logs` (Docker) > `backend/core/api/logs` (dev fallback).

### Loggers

| Logger                | Purpose                                      | Level   |
|-----------------------|----------------------------------------------|---------|
| `app`                 | Base application logger                      | Env-based |
| `app.events`          | Event-specific logging                       | Env-based |
| `compliance.audit`    | Audit events (2-year GDPR retention)         | INFO    |
| `compliance.financial`| Financial events (10-year AO SS 147 retention)| INFO    |
| `uvicorn.*`           | Web server logs                              | WARNING (prod) / INFO (dev) |
| `httpx`, `httpcore`   | HTTP client logs                             | WARNING |

### Sensitive Data Redaction

All logs pass through `SensitiveDataFilter` which redacts:

- Email addresses -> `***@***.***`
- IP addresses (IPv4/IPv6) -> `[REDACTED_IP]`
- UUIDs -> `[REDACTED_ID]` (except `user_id` in compliance logs)
- Passwords, API keys/tokens/secrets -> `[REDACTED]`
- Bearer tokens -> `Bearer [REDACTED]`

### JSON Output Format

```json
{"timestamp": "2026-03-24T12:00:00", "level": "INFO", "name": "app.services.cache", "message": "Cache operation completed"}
```

Console (stdout) output uses the same JSON format, compatible with Docker logging and Promtail/Loki ingestion.

### Environment Variables

| Variable                      | Default                         | Description                                       |
|-------------------------------|---------------------------------|---------------------------------------------------|
| `LOG_LEVEL`                   | `WARNING` (prod) / `INFO` (dev) | Minimum log level                                 |
| `LOG_DIR`                     | `/app/logs` or relative fallback| Log file directory                                |
| `LOG_MAX_BYTES`               | `10485760` (10 MB)              | Max size per `api.log` before rotation            |
| `LOG_BACKUP_COUNT`            | `5`                             | Number of `api.log` backups                       |
| `COMPLIANCE_LOG_WHEN`         | `D`                             | Rotation period: `D`/`W`/`M`                      |
| `COMPLIANCE_LOG_INTERVAL`     | `1`                             | Rotation interval                                 |
| `COMPLIANCE_LOG_BACKUP_COUNT` | `0`                             | `0` = keep all (never auto-delete)                |
| `SERVER_ENVIRONMENT`          | `development`                   | Controls default log level                        |
| `LOG_FILTER_DEBUG`            | -                               | Enable filter debugging (`1`/`true`/`yes`)        |

## Edge Cases

- If the logs directory is not writable, file handlers are silently skipped and only console logging is active.
- `COMPLIANCE_LOG_BACKUP_COUNT=0` means compliance logs accumulate indefinitely. Manual archival to cold storage (S3/Glacier) is required based on legal retention periods.
- Docker containers mount `./api/logs` to `/app/logs` (see `backend/core/docker-compose.yml`).

## Related Docs

- [Sensitive Data Redaction](../privacy/sensitive-data-redaction.md)
- [Admin Console Log Forwarding](./admin-console-log-forwarding.md) -- client-side logs to OpenObserve
- Promtail config: `backend/core/monitoring/promtail/promtail-config.yaml`
