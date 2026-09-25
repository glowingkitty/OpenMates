# Events Search — Provider Architecture & Data Reference

**Last updated:** 2026-09-24
**Skill:** `backend/apps/events/skills/search_skill.py`
**Providers:** `backend/apps/events/providers/`

## Provider Overview

| Provider | Data Source | Auth | Proxy | Cost per Search |
|----------|-----------|------|-------|----------------|
| **Meetup** | GraphQL (`gql2`) | None | Webshare residential | ~$0.00002 (proxy bandwidth) |
| **Luma** | REST API (`api2.luma.com`) | None | Webshare fallback | Free (direct) / pennies (proxy) |
| **Eventbrite** | Destination search API | None | Webshare fallback | Free (direct) / pennies (proxy) |
| **Resident Advisor** | GraphQL (`ra.co/graphql`) | None | None | Free (direct httpx) |
| **Siegessäule** | GraphQL (`siegessaeule.de/graphql/`) | None | Webshare residential | ~$0.00002 (proxy bandwidth) |
| **Berlin Philharmonic** | Concert calendar API | None | None | Free (direct) |
| **Conference schedules** | Pretalx/C3VOC exports | None | None | Free (direct) |

SerpAPI [deprecated its Google Events API](https://serpapi.com/google-events-api) and says it no longer accepts new requests. The event-search skill no longer calls that engine. Event results from SerpAPI's general Google Search API would require a separate integration decision.

## Data Fields Per Provider

### Core Fields

| Field | Meetup | Luma | RA | Siegessäule |
|-------|--------|------|-----|-------------|
| `title` | Full | Full | Full | Full |
| `description` | Markdown 668-2904ch | Prose 1065-2000ch | Full+lineup 509-2086ch | HTML 84-641ch |
| `url` | meetup.com | lu.ma | ra.co | siegessaeule.de |
| `date_start` | ISO 8601 w/ TZ offset | ISO 8601 UTC | ISO 8601 | ISO 8601 |
| `date_end` | ISO 8601 | ISO 8601 | ISO 8601 | null (sometimes) |
| `timezone` | "Europe/Berlin" | "Europe/Berlin" | null | "Europe/Berlin" |
| `event_type` | "PHYSICAL"/"ONLINE" | "offline"/"online"/"hybrid" | "PHYSICAL" | "PHYSICAL" |

### Venue Fields

| Field | Meetup | Luma | RA | Siegessäule |
|-------|--------|------|-----|-------------|
| `venue.name` | Full | Sometimes null | Full | Full |
| `venue.address` | Street | Sometimes null | Full street | Full |
| `venue.city` | City | City | From area | "Berlin" |
| `venue.lat` | float | float | float | float |
| `venue.lon` | float | float | float | float |

### Social/Popularity Signals

| Field | Meetup | Luma | RA | Siegessäule |
|-------|--------|------|-----|-------------|
| `rsvp_count` | 120-181 typical | 48-208 | 156-595 (`attending`) | null |
| `is_paid` | bool | bool | bool | null |
| `fee` | `{amount: 7.0, currency: "EUR"}` | null (is_paid only) | `{amount: "18-22", currency: "EUR"}` | null |
| `organizer` | `{name, slug, id}` | `{name, avatar, slug}` | `{name}` (promoter) | null |
| `hosts` | — | Array w/ avatars | — | — |
| `image_url` | Meetup CDN | Luma CDN | RA CDN (flyerFront) | Siegessäule CDN |

### Provider-Specific Enrichment Fields

| Field | Provider | Description |
|-------|----------|-------------|
| `artists` | RA | Array of artist names (5-10 per event) |
| `genres` | RA | Array: "Techno", "House", "Trance", etc. |
| `minimum_age` | RA | Integer (18, 21, etc.) |
| `is_festival` | RA | Boolean |
| `tags` | Siegessäule | Array: "queer", "drag", "danceparty", etc. (3-7 per event) |
| `category` | Siegessäule | Section slug: clubs, bars, kultur, mix, sex |
| `siegessaeule_presents` | Siegessäule | Boolean (promoted events) |
| `cover_url` | Luma | Event cover image (fallback for image_url) |

## Current Sorting

Date ascending (`date_start`) by default. Optional Jev relevance ranking applies only when `relevance_criteria` is supplied.

## Signals Available for Smart Sorting

1. **Query relevance** — title/description match to user's search terms (all providers)
2. **Temporal proximity** — distance from now
3. **Popularity/attendance** — RSVP count from Meetup (120-181), Luma (48-208), RA (156-595)
4. **Venue quality** — address and coordinate completeness
5. **Data completeness** — events with venue, description, image rank higher
6. **Provider diversity** — avoid 10 results from one provider
7. **Genre/category match** — RA genres + Siegessäule categories for intent matching
8. **Geographic precision** — events with lat/lon vs events without
9. **Image availability** — events with images are more engaging
10. **Price transparency** — events with fee info vs unknown

## Architecture Notes

- General providers and relevant specialists run concurrently in auto mode
- Results merged with URL-based deduplication
- `_AUTO_PROVIDER_MULTIPLIER = 2` — requests 2x count per provider for merge headroom
- Provider aliases normalize LLM tool calls (e.g., "Resident Advisor" -> "resident_advisor")
- Siegessäule and Meetup require Webshare proxy from datacenter IPs
- RA and Luma work with direct httpx from datacenter
- Firecrawl is NOT used in production — research only
