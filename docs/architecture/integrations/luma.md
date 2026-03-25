---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/events/providers/luma.py
  - scripts/api_tests/test_luma_api.py
---

# Luma Integration

> Reverse-engineered integration with Luma's internal API (`api2.luma.com`) for discovering public events across 78 featured cities. No API key required.

## Why This Exists

Luma is popular in tech/startup communities for event discovery. The official `public-api.luma.com` requires a paid Luma Plus subscription and is organizer-scoped only (no discovery). This integration uses the internal API discovered by intercepting browser network traffic on city pages like `luma.com/berlin`.

## How It Works

### Endpoints

**Event Search (primary):** `GET https://api2.luma.com/discover/get-paginated-events`
- `discover_place_api_id` (required) -- city ID (e.g., `discplace-gCfX0s3E9Hgo3rG` for Berlin)
- `pagination_limit` (max ~40), `query` (keyword filter), `pagination_cursor` (next page)

**City Bootstrap:** `GET https://api2.luma.com/discover/bootstrap-page` -- returns all 78 featured places. Use to refresh `CITY_PLACE_IDS` mapping.

**City Details:** `GET https://api2.luma.com/discover/get-place-v2` -- metadata for a specific city.

### Headers and Auth

No API key. Requires browser-like headers: `User-Agent`, `Origin: https://luma.com`, `Referer: https://luma.com/discover` (for CORS).

### Proxy Fallback (`luma.py`)

All requests attempted direct first. On HTTP 403/429/5xx or connection error, retried once via Webshare rotating residential proxy (same credentials as Meetup provider).

### Output Schema (`search_events_async()`)

Normalized event objects with: `id`, `provider` ("luma"), `title`, `url` (`https://lu.ma/<slug>`), `date_start`/`date_end` (ISO 8601), `timezone`, `event_type` (offline/online/hybrid), `venue` (name, address, coordinates), `organizer`, `hosts`, `rsvp_count`, `is_paid`, `cover_url`, `city`, `country`.

### City Coverage

78 cities across Europe (24), Middle East/Africa (5), South Asia (3), East Asia/SE Asia (10), North America (26), Latin America (6), Oceania (4). Cities NOT on this list are not supported -- no arbitrary location search.

## Edge Cases

- **No description in list response** -- requires separate per-event fetch
- **Guest count may be null** -- organizer can hide guest list
- **Partial addresses** -- `geo_address_visibility: "guests-only"` events show city only
- **No date range filter** -- returns future events ascending; filter client-side
- **No category filter** -- `query` param is fuzzy/ranking-based, not strict
- **Max page size** -- ~40 events per request

## Fragility Risks

- Luma could change or auth-gate endpoints at any time
- City `discplace-*` IDs are hardcoded -- refresh via bootstrap endpoint if events stop returning
- Monitor for HTTP 401/403 indicating auth was added
- Check `lu.ma/robots.txt` before deployment
- Polite rate limiting: 1.2s between paginated requests (already implemented)
- Cache results 15-30 minutes; stop pagination at 2-3 pages

### Cost

Zero direct API cost. Server bandwidth only (~5-20 KB per page).

## Related Docs

- [Media Generation](./media-generation.md) -- another integration using screenshots
- Test script: `scripts/api_tests/test_luma_api.py`
