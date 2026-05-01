# Train Connection API Research (Europe)

> Status: Research complete, pending Omio affiliate application
> Date: 2026-04-30
> Related: `backend/apps/travel/`, `backend/apps/travel/providers/transitous_provider.py`

## Goal

Find an API that returns full European train connection details (times, operator, price, duration, changes) **with a booking link per connection** to an external provider. We do NOT want to be the ticket seller — that brings refund liability, consumer protection obligations, VAT handling, etc.

## Current State

| Provider | What it does | Status |
|----------|-------------|--------|
| SerpAPI (Google Flights) | Flight search with prices + booking links | Production |
| Transitous / MOTIS | Train routes & timetables, no prices, no booking | Stub (`transitous_provider.py`) |
| Duffel | Flights only | Test file exists |

The `search_connections` skill already has `transport_methods: ["train"]` in the schema but returns empty results because `TransitousProvider` is a stub.

## Requirements

1. Returns full connection details per result (departure/arrival times, duration, changes, operator/carrier, price)
2. Returns a **booking link per connection** to an external booking provider
3. We are an affiliate/comparison layer, NOT the ticket seller
4. Accessible to individual developers (not enterprise-only)
5. European coverage (domestic + cross-border)

## APIs Evaluated

### Omio Affiliate Search API — Recommended

**Model**: Affiliate — we search via their API, get connection details + deeplink per result, user clicks through to Omio to book. Commission per redirect/booking. We are NOT the seller.

**Response fields per connection** (from their OpenAPI spec):
- `departureLocation`, `arrivalLocation`
- `departureDateAndTime`, `arrivalDateAndTime`
- `durationInMinutes`, `numberOfStops`
- `carrier` (operator name)
- `price`, `currency`
- `travelMode` (train, bus, ferry, flight)
- `deeplink` — URL to Omio booking page for that specific connection

**Request parameters**:
- `departureLocation`, `arrivalLocation` (city names)
- `departureDate` (YYYY-MM-DD)
- `preferredTravelMode` (train, bus, ferry, flight)
- `currency` (ISO 4217)
- `limit`, `offset`
- `minDepartureTime`, `maxDepartureTime`
- `sortingField` (price, departureTime, arrivalTime)
- `sortingOrder` (ascending, descending)

**Coverage**: 1,000+ transport partners across Europe, trains + buses + ferries + flights.

**Access**:
- Signup via impact.com: `app.impact.com/campaign-promo-signup/GoEuro-Travel-Partner-Program.brand`
- Free to join, anyone with a website/app
- Review within 14 business days
- Contact: `affiliates@omio.com`

**Commission**: Performance-based per redirect, scales with ROI. Minimum EUR 100 payout threshold.

**Open question**: Whether the Search API is available to all affiliates or only higher-tier partners. The ChatGPT plugin endpoint (`omio.com/b2b-chatgpt-plugin/schedules`) is locked behind auth, but the affiliate Search API may be a separate endpoint. Need to apply and ask.

**Next step**: Email `affiliates@omio.com`:
> "We're building a travel assistant app and want to integrate your Search API to show train connections with booking deeplinks. Is the Search API available to affiliate partners, and what are the requirements to get API credentials?"

### All Aboard — Full booking API (not affiliate model)

**Model**: You ARE the ticket seller. The API handles search → pricing → booking → PDF ticket delivery. No booking links to external providers — you book through the API directly.

**Why rejected**: Selling tickets directly means we're the merchant of record — refund liability, consumer protection, VAT, etc. Not our desired business model.

**Coverage (for reference)**: DB, SNCF, TGV, OUIGO, Eurostar, Trenitalia, Trenord, Renfe, OBB, SBB, NS, SNCB, SJ, Vy, DSB, CD, ZSSK, MAV, CFL, plus Interrail/Eurail passes. GraphQL API, self-serve signup at `allaboard.eu/join`, docs at `docs.allaboard.eu`.

### SerpAPI Google Trains — Search only, no booking links

**Model**: Scrape Google Search answer box (`transport_options` type) for train connections.

**What it returns**: Departure/arrival times, duration, fare, changes, summary (cheapest/fastest/daily count).

**Tested successfully** on 8+ European routes (domestic + cross-border). Costs 1 SerpAPI credit per query.

**Why rejected as primary**: No booking links per connection, no operator/carrier info, locale-dependent (`gl=us/gb/ch` only), currency tied to locale, no date API parameter. Could serve as a supplementary data source.

### Trainline Deep Links — No search API

**Model**: Affiliate via Tradedoubler/Partnerize. You construct booking URLs with route+date, user lands on Trainline's pre-filled search results.

**Deep link format**: `https://www.thetrainline.com/book/results?journeySearchType=single&origin={station}&destination={station}&outwardDate={YYYY-MM-DDTHH:MM:SS}`

**Why rejected as primary**: No Search API — can't get connection details from Trainline, only link to them. Would need a separate data source + constructed links. The link opens the results page, not a specific connection.

**Coverage**: 270+ operators, 45 countries — largest in Europe.

### Others Evaluated

| Provider | Model | Why rejected |
|----------|-------|-------------|
| Trainline Partner Solutions (TPS) | Enterprise API | Enterprise-only, ~12 weeks integration, no self-serve |
| Distribusion | Enterprise API | Partnership required, no self-serve |
| Rail Europe (ERA) | Agency/partner API | Commercial agreement required |
| Amadeus / Sabre / Travelport | GDS (SOAP) | Enterprise contracts, complex, expensive |
| DB transport.rest (v6) | Community wrapper | HAFAS shut down, low rate limits, Germany-only, no prices |
| Lyko | Booking API | 8 operators only, unclear access, no docs |
| Save A Train | Booking API | Small company, unclear coverage, no public docs |
| Google Transport Features API | Partner program | Requires formal Google partnership, not self-serve |

## Fallback Strategy

If Omio Search API access is denied or too limited:

1. **SerpAPI trains** for connection data (times, prices) — already integrated provider
2. **Trainline deep links** for booking — construct URL per route+date
3. **Transitous/MOTIS** for supplementary timetable data — already stubbed

This gives us search results with prices + a booking link, but the booking link opens a search results page (not a specific connection) and there's no operator info from SerpAPI.

## SerpAPI Trains — Technical Details (for fallback)

Query: `engine=google`, `q="train {origin} to {destination} tickets"`, `gl=gb`

Returns `answer_box.type = "transport_options"` with:
- `title`, `from`, `to`, `date`, `cheapest`, `fastest`, `daily_trains`
- `routes[]`: `time`, `duration`, `fare`, `changes`, `fast`

Limitations:
- Only triggers with `gl=us`, `gl=gb`, `gl=ch` — NOT `gl=de/fr/it/es/nl/at`
- No operator/carrier info per connection
- Currency tied to locale (GBP for `gl=gb`)
- Date must be in query text, no API parameter
- No booking links

Tested routes (all working with `gl=gb`):
- Munich → Berlin: 36 connections, 34 with fares
- Paris → London: 24 connections, 24 with fares
- Rome → Milan: 84 connections, 83 with fares
- Amsterdam → Brussels: 39 connections, 34 with fares
- Barcelona → Madrid: 38 connections, 38 with fares
- Vienna → Prague: 20 connections, 8 with fares
- Stockholm → Copenhagen: 36 connections, 19 with fares
- Hamburg → Frankfurt: 39 connections, 38 with fares

---

## Deutsche Bahn Internal API — Direct Price Access (Reverse-Engineered)

> Added: 2026-05-01
> Source: Reverse-engineered from bahn.de, DB Navigator app, and the [db-vendo-client](https://github.com/public-transport/db-vendo-client) open-source project.

Deutsche Bahn has **no official public API for prices**. However, two internal APIs used by their own products (bahn.de and DB Navigator app) return journey connections **with prices**, require **no API key**, and are well-documented by the open-source community.

### Available APIs

| API | Base URL | Used by | API Key | Prices |
|-----|----------|---------|---------|--------|
| Vendo Navigator API | `https://app.vendo.noncd.db.de/mob/` | DB Navigator app | No | Yes |
| Vendo bahn.de API | `https://int.bahn.de/web/api/` | bahn.de website | No | Yes |
| Old Sparpreis API | `https://ps.bahn.de/preissuche/` | (dead, DNS gone) | - | - |

**Recommended: Navigator API** — more stable, used by the official app, no bot detection (unlike bahn.de which has aggressive Akamai protection).

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/mob/angebote/fahrplan` | POST | **Route search with prices** |
| `/mob/angebote/tagesbestpreis` | POST | Best price per day (calendar view) |
| `/mob/angebote/recon` | POST | Refresh journey (detailed ticket options) |
| `/mob/location/search` | POST | Station/location autocomplete |
| `/mob/zuglauf/{id}` | GET | Train run details |
| `/mob/bahnhofstafel/abfahrt` | GET | Departure board |

### Request Format — POST `/mob/angebote/fahrplan`

**Headers:**
```
Content-Type: application/x.db.vendo.mob.verbindungssuche.v9+json
Accept: application/x.db.vendo.mob.verbindungssuche.v9+json
X-Correlation-ID: {uuid}_{uuid}
Accept-Language: en
```

**Body (Berlin → München, 1 adult, 2nd class, no BahnCard):**
```json
{
  "autonomeReservierung": false,
  "einstiegsTypList": ["STANDARD"],
  "fahrverguenstigungen": {
    "deutschlandTicketVorhanden": false,
    "nurDeutschlandTicketVerbindungen": false
  },
  "klasse": "KLASSE_2",
  "reiseHin": {
    "wunsch": {
      "abgangsLocationId": "A=1@O=Berlin Hbf@X=13369549@Y=52525589@U=80@L=8011160@B=1@p=1234567890@",
      "zielLocationId": "A=1@O=München Hbf@X=11558339@Y=48140229@U=80@L=8000261@B=1@p=1234567890@",
      "alternativeHalteBerechnung": true,
      "verkehrsmittel": ["ALL"],
      "zeitWunsch": {
        "reiseDatum": "2026-05-15T10:00:00.000+02:00",
        "zeitPunktArt": "ABFAHRT"
      }
    }
  },
  "reisendenProfil": {
    "reisende": [
      {
        "ermaessigungen": ["KEINE_ERMAESSIGUNG KLASSENLOS"],
        "reisendenTyp": "ERWACHSENER"
      }
    ]
  },
  "reservierungsKontingenteVorhanden": false
}
```

### Key Request Parameters

| Parameter | Values | Notes |
|-----------|--------|-------|
| `klasse` | `KLASSE_1`, `KLASSE_2` | Travel class |
| `zeitPunktArt` | `ABFAHRT`, `ANKUNFT` | Departure or arrival time |
| `verkehrsmittel` | `["ALL"]`, `["ICE"]`, `["EC_IC"]`, `["REGIONAL"]` | Transport filter |
| `reisendenTyp` | `ERWACHSENER` (27-64), `SENIOR` (65+), `JUGENDLICHER` (15-26), `KIND` (6-14) | Traveller type |
| `ermaessigungen` | `KEINE_ERMAESSIGUNG KLASSENLOS`, `BAHNCARD25 KLASSE_2`, `BAHNCARD50 KLASSE_2` | Discount cards |
| `maxUmstiege` | integer | Max transfers |
| `fahrradmitnahme` | boolean | Bike transport |
| `deutschlandTicketVorhanden` | boolean | Has Deutschland-Ticket |

**Location IDs** use HAFAS format: `A=1@O={name}@X={lon*1e6}@Y={lat*1e6}@U=80@L={evaNumber}@B=1@p=...@`
The `L=` value is the EVA station number. Obtain via `/mob/location/search`.

### Response Format (simplified)

```json
{
  "verbindungen": [
    {
      "verbindungsAbschnitte": [
        {
          "abgangsOrt": { "name": "Berlin Hbf", "extId": "8011160" },
          "ankunftsOrt": { "name": "München Hbf", "extId": "8000261" },
          "abgangsDatum": "2026-05-15T10:00:00",
          "ankunftsDatum": "2026-05-15T14:00:00",
          "verkehrsmittel": { "name": "ICE 1007", "produktGattung": "ICE" },
          "abgangsGleis": "8",
          "ankunftsGleis": "22"
        }
      ],
      "angebotsPreis": { "betrag": 29.90, "waehrung": "EUR" },
      "abPreis": { "betrag": 17.90, "waehrung": "EUR" },
      "hasTeilpreis": false,
      "rekontext": "..."
    }
  ]
}
```

**Price fields:**
- `angebotsPreis.betrag` — Flexpreis (full-price ticket)
- `abPreis.betrag` — Starting from price (Sparpreis / cheapest)
- `hasTeilpreis` — Partial fare flag (only covers part of the route)
- Use `rekontext` with `/mob/angebote/recon` to get detailed ticket options (Super Sparpreis, Sparpreis, Flexpreis with conditions)

### Common EVA Station Numbers

| Station | EVA |
|---------|-----|
| Berlin Hbf | 8011160 |
| München Hbf | 8000261 |
| Frankfurt(Main)Hbf | 8000105 |
| Hamburg Hbf | 8002549 |
| Köln Hbf | 8000207 |
| Stuttgart Hbf | 8000096 |
| BER Airport | 8011201 |

### Rate Limiting & Anti-Bot Notes

- **Navigator API** (`app.vendo.noncd.db.de`) — no known bot detection, designed for mobile app traffic. ~100 req/min seems safe.
- **bahn.de API** (`int.bahn.de`) — aggressive Akamai bot detection, returns 403/751 for automated browsers. Avoid for server-side use.
- Use a realistic `User-Agent` (e.g., `DBNavigator/Android/25.18.2`).
- No official rate limits documented. These are unofficial APIs — DB can change or block them at any time.

### Reference Implementation

The [db-vendo-client](https://github.com/public-transport/db-vendo-client) (JS/Node, 190 stars, active as of Oct 2025) is a full client for both APIs. It handles request formatting, response parsing, price extraction, and pagination. Use as reference for our Python provider.

### Relevance to OpenMates

This API is useful as a **Germany-specific fallback** or supplement to Omio:
- **Pro:** Free, no API key, real-time prices, detailed ticket breakdown, platform numbers
- **Con:** Germany-only (some cross-border via DB), unofficial/unstable, no booking deeplinks, no affiliate revenue
- If used, provider wrapper goes in `backend/shared/providers/deutsche_bahn.py`
- Two-step flow: location search → route search with prices
- Cache station EVA lookups (they rarely change)
