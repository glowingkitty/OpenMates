# Logging System

## Overview

The OpenMates backend uses Python's standard `logging` module with JSON formatting via `pythonjsonlogger`. The system is configured to output logs to both console (stdout) and files, with automatic log rotation to prevent infinite growth.

## Architecture

### Logging Framework
- **Base Library**: Python's `logging` module
- **JSON Formatter**: `pythonjsonlogger.jsonlogger.JsonFormatter`
- **Handler Types**: 
  - `RotatingFileHandler` for regular logs (size-based rotation)
  - `TimedRotatingFileHandler` for compliance logs (time-based rotation, no auto-deletion)
  - `StreamHandler` for console output
- **Configuration Method**: `logging.config.dictConfig()` using dictionary-based configuration

### Main Configuration Files

The logging system is configured in:
- [`backend/core/api/app/utils/setup_logging.py`](../../backend/core/api/app/utils/setup_logging.py) - Main logging configuration for API
- [`backend/core/api/app/utils/setup_compliance_logging.py`](../../backend/core/api/app/utils/setup_compliance_logging.py) - Compliance-specific logging setup
- [`backend/core/api/app/utils/log_filters.py`](../../backend/core/api/app/utils/log_filters.py) - Sensitive data redaction filters

## Log Files

### Location

Log files are stored in a configurable directory, determined in this order:
1. `LOG_DIR` environment variable (if set)
2. `/app/logs` (if exists - used in Docker containers)
3. `backend/core/api/logs` (fallback for local development)

### Log Files

- **`api.log`** - Main application logs (INFO level and above)
- **`compliance.log`** - Compliance and audit logs (INFO level, user IDs preserved)

### Log Rotation

The system uses different rotation strategies for regular logs vs compliance logs:

#### Regular Logs (`api.log`)

Uses **size-based rotation** with limited retention:
- **Default Max Size**: 10MB per file (`LOG_MAX_BYTES` environment variable, default: `10485760` bytes)
- **Default Backup Count**: 5 backup files (`LOG_BACKUP_COUNT` environment variable, default: `5`)
- **Total Maximum**: ~50MB per log file (10MB × 5 backups + current file)

When a log file reaches the maximum size, it's rotated:
- Current file: `api.log` → `api.log.1`
- Previous backups: `api.log.1` → `api.log.2`, etc.
- Oldest backup (`api.log.5`) is deleted when rotation occurs

#### Compliance Logs (`compliance.log`)

Uses **time-based rotation** with **NO automatic deletion** for legal compliance:

⚠️ **CRITICAL**: Compliance logs are **NEVER automatically deleted**. They must be manually archived or deleted based on legal retention requirements (e.g., 10 years for tax/commercial law per privacy policy).

- **Default Rotation**: Daily (`COMPLIANCE_LOG_WHEN` environment variable, default: `D`)
- **Default Interval**: Every 1 day (`COMPLIANCE_LOG_INTERVAL` environment variable, default: `1`)
- **Default Backup Count**: `0` (unlimited - keep ALL rotated files)
- **Rotation Format**: `compliance.log.YYYY-MM-DD` (daily), `compliance.log.YYYY-WW` (weekly), or `compliance.log.YYYY-MM` (monthly)

**Why time-based for compliance logs?**
- Prevents single-file growth while preserving all historical data
- Makes it easier to locate logs by date for legal/audit purposes
- Ensures compliance logs are available when needed for legal requirements

**Manual Management Required:**
- Compliance logs accumulate indefinitely by default
- You must implement a separate archival/deletion process based on your legal requirements
- Consider archiving old compliance logs to cold storage (S3, etc.) before deletion

## Log Levels

### Environment-Based Defaults

- **Production**: `WARNING` (sensitive INFO logs disabled)
- **Development**: `INFO` (all log levels enabled)

Override via `LOG_LEVEL` environment variable: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### Logger Configuration

- **`app`** - Base application logger
- **`app.events`** - Event-specific logger
- **`compliance`** - Compliance/audit logger (always INFO level, user IDs preserved)
- **`uvicorn`**, **`uvicorn.error`**, **`uvicorn.access`** - Web server logs
- **`httpx`**, **`httpcore`** - HTTP client logs (WARNING level)

## Features

### Sensitive Data Redaction

All logs pass through [`SensitiveDataFilter`](../../backend/core/api/app/utils/log_filters.py) which automatically redacts:
- Email addresses
- IP addresses
- UUIDs (except `user_id` in compliance logs)
- Passwords
- API keys/tokens/secrets
- Bearer tokens

**Exception**: Compliance logs preserve `user_id` fields for audit purposes.

### JSON Format

All logs are formatted as JSON with the following structure:
```json
{
  "timestamp": "2024-01-01T12:00:00",
  "level": "INFO",
  "name": "app.services.cache",
  "message": "Cache operation completed"
}
```

### Console Output

Logs are also written to stdout (console) in JSON format, making them compatible with:
- Docker logging
- Promtail/Loki (see [`backend/core/monitoring/promtail/promtail-config.yaml`](../../backend/core/monitoring/promtail/promtail-config.yaml))
- Grafana dashboards

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_DIR` | `/app/logs` or `backend/core/api/logs` | Log file directory |
| `LOG_LEVEL` | `WARNING` (prod) / `INFO` (dev) | Minimum log level |
| `LOG_MAX_BYTES` | `10485760` (10MB) | Maximum size per regular log file before rotation |
| `LOG_BACKUP_COUNT` | `5` | Number of backup files to keep for regular logs |
| `COMPLIANCE_LOG_WHEN` | `D` | Compliance log rotation: `D` (daily), `W` (weekly), `M` (monthly) |
| `COMPLIANCE_LOG_INTERVAL` | `1` | Compliance log rotation interval (e.g., every N days/weeks/months) |
| `COMPLIANCE_LOG_BACKUP_COUNT` | `0` | Compliance log backups to keep (`0` = keep ALL, no auto-deletion) |
| `SERVER_ENVIRONMENT` | `development` | Environment (affects default log level) |
| `LOG_FILTER_DEBUG` | - | Enable filter debugging (`1`, `true`, `yes`) |

**Important Notes:**
- `COMPLIANCE_LOG_BACKUP_COUNT=0` means compliance logs are **never automatically deleted**
- Set `COMPLIANCE_LOG_BACKUP_COUNT` to a number (e.g., `3650` for ~10 years of daily logs) if you want automatic deletion after a retention period
- However, **automatic deletion may violate legal requirements** - consult legal/compliance team before changing this

### Docker Configuration

Logs are mounted from the host at `./api/logs` to `/app/logs` in containers (see [`backend/core/docker-compose.yml`](../../backend/core/docker-compose.yml)).

## Usage Examples

### Standard Logger
```python
import logging

logger = logging.getLogger(__name__)
logger.info("Application started")
logger.error("An error occurred", exc_info=True)
```

### Event Logger
```python
from logging import getLogger

event_logger = getLogger("app.events")
event_logger.info("User registration process started")
```

### Compliance Logger
```python
from logging import getLogger

compliance_logger = getLogger("compliance")
compliance_logger.info({
    "event": "user_login",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "status": "success"
})
```

## Compliance Log Management

### Legal Requirements

Compliance logs must be retained according to legal requirements:
- **Tax/Commercial Law**: Up to 10 years (per privacy policy)
- **GDPR**: Varies by jurisdiction and data type
- **Industry Regulations**: May have specific retention requirements

### Best Practices

1. **Never Auto-Delete**: Keep `COMPLIANCE_LOG_BACKUP_COUNT=0` (default) to prevent accidental deletion
2. **Regular Archival**: Implement a separate process to archive old compliance logs to cold storage (S3, Glacier, etc.)
3. **Retention Policy**: Document your retention policy and ensure manual deletion only occurs after legal retention periods
4. **Audit Trail**: Maintain records of when compliance logs are archived or deleted
5. **Backup Strategy**: Ensure compliance logs are included in your backup strategy

### Example Archival Process

```bash
# Example: Archive compliance logs older than 7 years to S3
# Run this as a scheduled task (cron, etc.)
aws s3 sync /app/logs/compliance.log.* s3://your-bucket/compliance-logs/ \
  --exclude "compliance.log" \
  --exclude "compliance.log.$(date +%Y)*" \
  --exclude "compliance.log.$(date -d '1 year ago' +%Y)*" \
  --exclude "compliance.log.$(date -d '2 years ago' +%Y)*" \
  # ... keep recent years locally
```

**Important**: Only delete compliance logs after:
1. Confirming legal retention period has passed
2. Verifying logs are archived in secure, accessible storage
3. Documenting the deletion in your audit trail

## Related Documentation

- [Sensitive Data Redaction](../architecture/sensitive_data_redaction.md) - Detailed information about data filtering
- [Monitoring Setup](../../backend/core/monitoring/) - Promtail/Loki configuration for log aggregation
- [Privacy Policy](../../shared/docs/privacy_policy.yml) - Data retention policies

