---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/services/web_analytics_service.py
  - backend/core/api/app/routes/analytics_beacon.py
  - backend/core/api/app/tasks/celery_config.py
---

# Analytics

> Privacy-preserving, first-party analytics using aggregate-only Redis counters flushed to Directus. No PII, no cookies, no tracking identifiers.

## Why This Exists

OpenMates needs usage visibility (traffic trends, signup funnel, app usage) without compromising user privacy. All data is stored as daily aggregate counters -- no individual event records are kept.

## How It Works

### Data Flow

```
Browser POST /v1/analytics/beacon (after page load)
  -> analytics_beacon.py -> WebAnalyticsService
  -> HINCRBY / PFADD (atomic Redis ops)
  -> Redis hash: web:analytics:daily:YYYY-MM-DD
  -> Celery Beat: flush every 10 min to Directus (web_analytics_daily)
  -> Admin dashboard: GET /v1/admin/server-stats
```

### What Is Collected

**Web Traffic (`web_analytics_daily`):** page loads, approximate unique visits (HyperLogLog, ~0.81% error), country distribution (GeoIP), device class, browser family, OS family, referrer domains, screen size class, session duration buckets.

Unique visits: `SHA256(truncated_ip + ua_family + date)` added to a Redis HyperLogLog. No raw data stored.

**Signup Funnel (`signup_funnel_daily`):** step-by-step counters (started_basics, email_confirmed, auth_password_setup, auth_passkey_setup, recovery_key_saved, reached_payment, payment_completed, payment_completed_eu/non_eu, auto_topup_setup).

**App Analytics (`app_analytics_daily`):** daily rollup by app_id, skill_id, model_used, focus_mode_id, settings_memory_type. Raw events aggregated at 03:00 UTC.

**Financial (`server_stats_global_daily`):** purchases, gift cards, subscriptions (JSON), total input/output tokens.

**Content Views (`content_views_daily`):** aggregate views of intro pages, legal docs, example chats.

### Redis Key Structure

| Key                              | Type        | Purpose                               |
|----------------------------------|-------------|---------------------------------------|
| `web:analytics:daily:YYYY-MM-DD` | Hash        | All daily counters (e.g., `devices:mobile`, `countries:DE`) |
| `web:analytics:hll:YYYY-MM-DD`   | HyperLogLog | Unique visit estimation               |

### Celery Tasks

| Task                              | Queue          | Schedule        |
|-----------------------------------|----------------|-----------------|
| `web_analytics.flush_to_directus` | `server_stats` | Every 10 min    |
| `app_analytics.aggregate_daily`   | `persistence`  | Daily 03:00 UTC |

### Session Duration via WebSocket

`ConnectionManager.connect()` records `time.monotonic()`; `_finalize_disconnect()` computes duration and calls `web_analytics_service.record_session_duration()`, bucketing into: `<30s`, `30s-2m`, `2m-5m`, `5m-15m`, `15m-30m`, `30m-1h`, `1h+`.

### Graceful Shutdown

On SIGTERM, `main.py` calls `web_analytics_service.dump_to_disk()` which serializes the current-day Redis hash to `/shared/cache/web_analytics_backup.json`. On startup, `restore_from_disk()` restores counters to Redis.

## Edge Cases

- **GeoIP database missing:** Country data recorded as `"unknown"`. Logged as warning at startup, not error. Database path: `GEOLITE2_DB_PATH` (default `/shared/geoip/GeoLite2-Country.mmdb`).
- **Redis unavailable between flush cycles:** Data for that interval is lost (no disk backup until SIGTERM).

## Privacy Compliance

No PII stored or processed. IP addresses used transiently for GeoIP only, never written to storage. No cookies, no tracking identifiers, no consent banner required. See Privacy Policy (`frontend/packages/ui/src/i18n/sources/legal/privacy.yml`, section `aggregate_analytics`).

## Related Docs

- Admin dashboard: `/settings/server` via `GET /v1/admin/server-stats`
- Directus collections: `web_analytics_daily`, `signup_funnel_daily`, `app_analytics_daily`, `content_views_daily`
- Schema definitions: `backend/core/directus/schemas/`
