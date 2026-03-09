# Luma.com (lu.ma) API Integration Summary

## Overview

Luma is an event management platform popular in the tech/startup community. Its
discover feature lists upcoming public events in 78 featured cities globally.

This integration uses **Luma's internal API** (discovered by reverse-engineering
the luma.com web app's network traffic) — not the official Luma Plus API.

## Reverse-Engineered Integration Warning

This integration is NOT based on an official API. The official `public-api.luma.com`
requires a paid Luma Plus subscription and is organiser-scoped only (no discovery).

The internal `api2.luma.com` API was discovered by intercepting browser network
requests when navigating to `luma.com/berlin` and similar city pages.

### Fragility Risks

- Luma could change or auth-gate these endpoints at any time
- The `discplace-*` IDs for featured cities are hardcoded — if Luma adds or changes
  cities, the mapping in `CITY_PLACE_IDS` would need to be refreshed
- No SLA or guaranteed stability

### Maintenance Requirements

- If events stop returning, re-inspect browser network traffic on a Luma city page
- The city ID map can be refreshed by calling the bootstrap endpoint:
  `GET https://api2.luma.com/discover/bootstrap-page?featured_place_api_id=discplace-gCfX0s3E9Hgo3rG`
- Monitor for HTTP 401/403 responses which would indicate auth was added

### Legal Considerations

- Luma's robots.txt: https://lu.ma/robots.txt — check before deployment
- Implement respectful rate limiting (1.2s between paginated requests — already in code)
- Cache results to minimise requests — events don't change minute-by-minute
- These are public event listings that Luma deliberately makes visible to all users

## Authentication

- **Type:** None required
- **Headers needed:** Standard browser `User-Agent`, plus `Origin: https://luma.com`
  and `Referer: https://luma.com/discover` (required for CORS)
- **Vault key:** None (no API key)

## Endpoints Used

### 1. Event Search (primary endpoint)

- **URL:** `GET https://api2.luma.com/discover/get-paginated-events`
- **Purpose:** Retrieve upcoming public events for a specific featured city
- **Query parameters:**
  - `discover_place_api_id` (required) — city place ID (e.g. `discplace-gCfX0s3E9Hgo3rG` for Berlin)
  - `pagination_limit` (optional) — events per page (default 25, max ~40)
  - `query` (optional) — keyword search filter (server-side, e.g. "AI", "startup")
  - `pagination_cursor` (optional) — opaque cursor for next page (from `next_cursor` field)

**Example response structure:**
```json
{
  "entries": [
    {
      "api_id": "evt-xxx",
      "event": {
        "name": "AI Meetup Berlin",
        "start_at": "2026-03-12T18:00:00.000Z",
        "end_at": "2026-03-12T21:00:00.000Z",
        "timezone": "Europe/Berlin",
        "location_type": "offline",
        "url": "abc123",
        "cover_url": "https://images.lumacdn.com/...",
        "geo_address_info": {
          "city": "Berlin",
          "country": "Germany",
          "full_address": "Torstrasse 1, 10119 Berlin, Germany",
          "country_code": "DE"
        },
        "coordinate": { "latitude": 52.527, "longitude": 13.415 }
      },
      "calendar": { "name": "Organiser Name", "avatar_url": "..." },
      "hosts": [{ "name": "Host Name", "avatar_url": "..." }],
      "guest_count": 42,
      "ticket_info": { "is_paid": false }
    }
  ],
  "has_more": true,
  "next_cursor": "eyJzdi..."
}
```

### 2. City Bootstrap (city ID discovery)

- **URL:** `GET https://api2.luma.com/discover/bootstrap-page`
- **Purpose:** Returns all 78 featured place objects with slug/name/api_id
- **Query parameters:**
  - `featured_place_api_id` — any valid city place ID (used as context)
- **Use:** Refresh the `CITY_PLACE_IDS` map if cities change

### 3. City Place Details

- **URL:** `GET https://api2.luma.com/discover/get-place-v2`
- **Purpose:** Returns metadata for a specific city (name, description, event_count, coordinates)
- **Query parameters:**
  - `discover_place_api_id` — city place ID

## City Coverage

78 featured cities as of March 2026:

Europe: Helsinki, Stockholm, Copenhagen, Warsaw, Berlin, Hamburg, Prague, Vienna,
        Budapest, Amsterdam, Munich, Brussels, Zurich, London, Paris, Lausanne,
        Milan, Geneva, Dublin, Istanbul, Rome, Barcelona, Madrid, Lisbon

Middle East / Africa: Tel Aviv, Dubai, Lagos, Nairobi, Cape Town

South Asia: New Delhi, Mumbai, Bengaluru

East Asia / SE Asia: Tokyo, Hong Kong, Bangkok, Taipei, Seoul, Manila,
                     Kuala Lumpur, Singapore, Jakarta, Ho Chi Minh City

North America: Montreal, Boston, Toronto, New York, Waterloo, Philadelphia,
               Washington DC, Minneapolis, Calgary, Chicago, Vancouver, Seattle,
               Atlanta, Portland, Denver, Salt Lake City, Miami, Dallas, Houston,
               Austin, Las Vegas, San Francisco, Phoenix, Los Angeles, San Diego,
               Honolulu

Latin America: Mexico City, Medellín, Bogotá, Buenos Aires, São Paulo,
               Rio de Janeiro

Oceania: Brisbane, Sydney, Melbourne, Auckland

**Important:** Cities NOT on this list are not supported. There is no arbitrary
lat/lon search or free-text city name lookup in this API.

## Input / Output Structure

### Normalised Event Schema (output of `search_events()`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Luma event API ID (`evt-...`) |
| `provider` | str | Always `"luma"` |
| `title` | str | Event name |
| `description` | None | Not available on list endpoint (requires individual fetch) |
| `url` | str | Full event URL (`https://lu.ma/<slug>`) |
| `date_start` | str | ISO 8601 UTC start datetime |
| `date_end` | str\|None | ISO 8601 UTC end datetime |
| `timezone` | str | IANA timezone (e.g. `"Europe/Berlin"`) |
| `event_type` | str | `"offline"`, `"online"`, or `"hybrid"` |
| `venue` | dict\|None | Venue details (only for offline events) |
| `venue.name` | str\|None | Venue name/address label |
| `venue.full_address` | str\|None | Full formatted address |
| `venue.city` | str | City name |
| `venue.country` | str\|None | Country name |
| `venue.lat` | float\|None | Latitude |
| `venue.lon` | float\|None | Longitude |
| `organizer.name` | str | Organiser/calendar name |
| `organizer.avatar_url` | str\|None | Organiser avatar |
| `hosts` | list | List of host objects with name/avatar_url |
| `rsvp_count` | int\|None | RSVP count (None if organiser hid it) |
| `is_paid` | bool | Whether tickets are paid |
| `cover_url` | str\|None | Event cover image URL |
| `city` | str | City name |
| `country` | str\|None | Country name |

## Pricing

- **Free:** Completely free — no API key, no account, no rate limits documented
- **Cost:** Zero direct API cost
- **Indirect cost:** Server bandwidth only (responses ~5-20 KB per page)

## Limitations

- **City restriction:** Only 78 curated cities — no arbitrary location search
- **No description:** Event description is not included in list responses;
  requires a separate fetch to the individual event page
- **Guest count:** May be null if the organiser has hidden the guest list
- **Address visibility:** Some events have `geo_address_visibility: "guests-only"`,
  meaning the exact address is only shown after RSVP. The `geo_address_info` may
  be partial (city only, no street address) for such events
- **No date range filter:** Cannot filter by specific date range via API params —
  returns future events sorted ascending; filter client-side if needed
- **No category filter via API:** No `category` parameter available on
  `get-paginated-events`; category filtering is a separate UI feature
- **Keyword search is fuzzy/ranking-based:** The `query` parameter affects result
  scoring/ranking, not strict filtering; non-matching events may still appear
- **Max page size:** ~40 events per request

## Scaling Considerations

- **Caching:** Events change infrequently — cache results for 15-30 minutes
- **Rate limiting:** No documented limits, but use the 1.2s inter-page delay
- **Pagination:** For large result sets, stop at 2-3 pages to stay responsive
- **City ID refresh:** Call bootstrap endpoint monthly or if IDs start returning 404s

## Test Script

```bash
# Search AI events in Berlin
python scripts/api_tests/test_luma_api.py --city berlin --query AI --limit 10

# Browse upcoming events in San Francisco
python scripts/api_tests/test_luma_api.py --city sf --limit 8

# List all supported cities
python scripts/api_tests/test_luma_api.py --list-cities

# Run full test suite
python scripts/api_tests/test_luma_api.py

# JSON output
python scripts/api_tests/test_luma_api.py --city berlin --query AI --json
```
