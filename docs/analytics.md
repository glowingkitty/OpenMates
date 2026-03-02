# Analytics Architecture

OpenMates uses a privacy-preserving, first-party analytics system. No third-party analytics services are used, no cookies are set, and no personally identifiable information (PII) is ever stored.

---

## Design Principles

- **No PII stored anywhere.** IP addresses are used transiently for GeoIP lookup only, then discarded immediately. User-Agent strings are parsed to structured metadata (browser family, OS) and the raw string is never stored.
- **Aggregate-only storage.** All data is stored as daily aggregate counters in Redis, then flushed to Directus every 10 minutes by a Celery task. No individual event records are kept.
- **No cookies, no tracking identifiers.** The client beacon fires a lightweight POST after page load. No fingerprinting. No cross-site tracking.
- **Graceful shutdown persistence.** On SIGTERM, Redis counters are dumped to `/shared/cache/web_analytics_backup.json` and restored on next startup, preventing data loss during container restarts.
- **No GDPR consent required.** Because no personal data is collected, no consent banner is necessary for analytics.

---

## What Is Collected

### Web Traffic (`web_analytics_daily`)

| Field                      | Type    | Description                                                                        |
| -------------------------- | ------- | ---------------------------------------------------------------------------------- |
| `date`                     | string  | Date (YYYY-MM-DD)                                                                  |
| `page_loads`               | integer | Total page load events                                                             |
| `unique_visits_approx`     | integer | Approximate unique visits via HyperLogLog (~0.81% error)                           |
| `countries`                | JSON    | Country distribution (ISO 3166-1 alpha-2 keys, e.g. `{"DE": 500, "US": 300}`)      |
| `devices`                  | JSON    | Device class: mobile / tablet / desktop                                            |
| `browsers`                 | JSON    | Browser family + major version (e.g. `{"Chrome 120": 400}`)                        |
| `os_families`              | JSON    | OS family (e.g. `{"Windows": 300, "macOS": 200}`)                                  |
| `referrer_domains`         | JSON    | Referrer domain only, never full URL (e.g. `{"google.com": 200, "(direct)": 400}`) |
| `screen_classes`           | JSON    | Screen width class: sm / md / lg / xl                                              |
| `session_duration_buckets` | JSON    | Session duration distribution (e.g. `{"<30s": 100, "2m-5m": 80}`)                  |

**Session duration buckets:** `<30s`, `30s-2m`, `2m-5m`, `5m-15m`, `15m-30m`, `30m-1h`, `1h+`

**Screen classes (matches CSS breakpoints):** `sm` (<640px), `md` (640–1023px), `lg` (1024–1439px), `xl` (≥1440px)

**Unique visits estimation:** For each page view, a token is computed as `SHA256(truncated_ip + ua_family + date)` and added to a Redis HyperLogLog. This gives probabilistic unique-visit counts with ~0.81% error, with no raw data stored.

### Signup Funnel (`signup_funnel_daily`)

Daily counters incremented at backend signup endpoints:

| Field                      | When incremented                          |
| -------------------------- | ----------------------------------------- |
| `started_basics`           | Invite code validated (first signup step) |
| `email_confirmed`          | Email verified via link                   |
| `auth_password_setup`      | Password set up successfully              |
| `auth_passkey_setup`       | Passkey registered                        |
| `recovery_key_saved`       | Recovery key acknowledged                 |
| `reached_payment`          | User reached payment step                 |
| `payment_completed`        | First payment or gift card redeemed       |
| `payment_completed_eu`     | Payment from EU country                   |
| `payment_completed_non_eu` | Payment from non-EU country               |
| `auto_topup_setup`         | Subscription configured                   |

### App Analytics Daily (`app_analytics_daily`)

Daily aggregation of raw `app_analytics` events, rolled up by dimension combination:

| Field                  | Description                                        |
| ---------------------- | -------------------------------------------------- |
| `app_id`               | App identifier (e.g. `ai`, `web`, `pdf`)           |
| `skill_id`             | Skill identifier within the app                    |
| `model_used`           | LLM model name                                     |
| `focus_mode_id`        | Focus mode identifier                              |
| `settings_memory_type` | Memory type setting                                |
| `count`                | Number of events with this combination on this day |

### Financial Extensions (`server_stats_global_daily`)

Additional fields added to the existing server stats collection:

- `purchases` (JSON): purchase counts by type
- `gift_cards` (JSON): gift card redemptions by type
- `subscriptions` (JSON): subscription events by type
- `total_input_tokens` (integer): total LLM input tokens consumed
- `total_output_tokens` (integer): total LLM output tokens produced

### Content Views (`content_views_daily`)

Tracks views of intro pages, legal documents, and example chats — all aggregate, no user IDs.

---

## Architecture

### Data Flow

```
Browser
  ↓ POST /v1/analytics/beacon (after page load)
analytics_beacon.py
  ↓ record_page_view() / record_session_duration()
WebAnalyticsService
  ↓ HINCRBY / PFADD (atomic Redis operations)
Redis (web:analytics:daily:YYYY-MM-DD hash)
  ↓ every 10 min (Celery beat)
web_analytics_tasks.flush_to_directus()
  ↓
Directus (web_analytics_daily collection)
  ↓
Admin dashboard (GET /v1/admin/server-stats)
```

### WebSocket Session Duration (Phase 7)

```
ConnectionManager.connect()
  → self.connection_times[key] = time.monotonic()
ConnectionManager._finalize_disconnect()
  → duration = time.monotonic() - connect_time
  → web_analytics_service.record_session_duration(duration)
  → buckets into session_duration_buckets
```

### Redis Key Structure

| Key                              | Type        | Description                                           |
| -------------------------------- | ----------- | ----------------------------------------------------- |
| `web:analytics:daily:YYYY-MM-DD` | Hash        | All daily counters (page_loads, devices:mobile, etc.) |
| `web:analytics:hll:YYYY-MM-DD`   | HyperLogLog | Unique visit estimation                               |

Hash fields use `prefix:sub_key` format for JSON distribution fields, e.g.:

- `devices:mobile` → `300`
- `browsers:Chrome 120` → `400`
- `countries:DE` → `500`
- `session_duration_buckets:<30s` → `100`

These are collected by `_collect_json_fields()` in the flush task and serialized to JSON columns in Directus.

### Celery Tasks

| Task name                         | Queue          | Schedule        | Description                             |
| --------------------------------- | -------------- | --------------- | --------------------------------------- |
| `web_analytics.flush_to_directus` | `server_stats` | Every 10 min    | Flush Redis counters to Directus        |
| `app_analytics.aggregate_daily`   | `persistence`  | Daily 03:00 UTC | Aggregate raw events into daily summary |

### Graceful Shutdown

On SIGTERM, `main.py` calls `web_analytics_service.dump_to_disk()`, which serializes the current-day Redis hash to `/shared/cache/web_analytics_backup.json`. On startup, `restore_from_disk()` reads this file and restores the counters to Redis, preventing data loss if the container restarts between Celery flush cycles.

---

## GeoLite2 Setup

Country lookup uses the MaxMind GeoLite2-Country database (free, no API key required for the mmdb file).

**Path:** `/shared/geoip/GeoLite2-Country.mmdb`  
**Environment variable:** `GEOLITE2_DB_PATH` (defaults to the path above)

The database is optional — if it is missing or cannot be opened, country data is simply not recorded (all countries appear as `"unknown"`). This is logged as a warning at startup, not an error.

**To set up:**

1. Download `GeoLite2-Country.mmdb` from [MaxMind](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data)
2. Place it at `/shared/geoip/GeoLite2-Country.mmdb` on the server
3. Restart the API container — country data collection begins immediately

---

## Directus Collections

The following new collections are created by the schema definitions in `backend/core/directus/schemas/`:

- `web_analytics_daily`
- `signup_funnel_daily`
- `app_analytics_daily`
- `content_views_daily`

And `server_stats_global_daily` / `server_stats_global_monthly` are extended with new columns.

---

## Admin Dashboard

All analytics data is surfaced in the admin settings (`/settings/server`) via a single `GET /v1/admin/server-stats` API call that fetches all collections in parallel. The dashboard displays:

- Web Traffic chart (page loads / unique visits over 30 days)
- Top Countries (ranked bar list)
- Devices (ranked bar list)
- Top Browsers (ranked bar list)
- Session Duration (bucketed bar list)
- Top Referrers (ranked bar list)
- Signup Funnel (horizontal funnel chart)
- App Usage (ranked bar list)

---

## Privacy Compliance

Because all analytics data is genuinely aggregate and no PII is stored or processed:

- No GDPR consent banner is required for analytics
- No cookie notice is required for analytics
- IP addresses are processed for GeoIP only and never written to any storage
- The analytics section in the Privacy Policy (Section 11) documents what is collected

See the Privacy Policy (`frontend/packages/ui/src/i18n/sources/legal/privacy.yml`, keys `aggregate_analytics.*`) for the user-facing description.
