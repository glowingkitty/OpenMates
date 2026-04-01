# Home App — Platform Research Results

**Date:** 2026-03-28
**Task:** OPE-61

## Platform Status

| Platform | Method | httpx? | Proxy? | Data Quality | Status |
|---|---|---|---|---|---|
| **ImmoScout24** | Reversed mobile API | Yes | No | Excellent (20/page, structured JSON) | **Ready** |
| **Kleinanzeigen** | SSR HTML scraping | Yes | No | Good (20/page, full SSR) | **Ready** |
| **WG-Gesucht** | Sitemap + Detail API | Yes | No | Incredible (100+ fields, HAL+JSON) | **Ready** |
| **Immowelt** | No viable API found | No | N/A | N/A (SSR micro-frontends, no client API) | **Deprioritized** |

## ImmoScout24 — Mobile API (No Auth)

**Base URL:** `https://api.mobile.immobilienscout24.de`
**Required header:** `User-Agent: ImmoScout_27.12_26.2_._`

| Endpoint | Method | Purpose |
|---|---|---|
| `/search/total?searchType=region&realestatetype=X&geocodes=Y` | GET | Result count |
| `/search/list?searchType=region&realestatetype=X&geocodes=Y` | POST | Listings (body: `{"supportedResultListTypes":[],"userData":{}}`) |
| `/expose/{id}` | GET | Listing detail |

**Key params:**
- `searchType`: `region` (location) or `radius` (distance)
- `realestatetype`: `apartmentrent`, `apartmentbuy`, `houserent`, `housebuy`
- `geocodes`: `/de/berlin/berlin`, `/de/bayern/muenchen`, etc.

**Rate limiting:** 10 rapid requests — all 200, no blocking. Avg 138ms/req.
**Without User-Agent:** Rejected (non-JSON response).

**Fields returned:** id, title, price, size, address, image URL, link. Detail endpoint adds agent info, attributes, free text sections.

## Kleinanzeigen — SSR HTML Scraping

**Search URL pattern:** `https://www.kleinanzeigen.de/s-{category}/{city}/c{cat_code}l{loc_code}`

| Category | Code | Example |
|---|---|---|
| Apartments rent | c203 | `/s-wohnungen-mieten/berlin/c203l3331` |
| Apartments buy | c196 | `/s-eigentumswohnungen/muenchen/c196l6411` |
| Houses buy | c208 | `/s-haeuser-kaufen/hamburg/c208l9409` |

**Pagination:** `/seite:N/` appended to URL.
**Bot detection:** None — works even with `User-Agent: Mozilla/5.0 (compatible; Bot/1.0)`.
**Data in HTML:** Full SSR. `data-adid` attributes, `.ellipsis` title links, ad-listitem containers.

## WG-Gesucht — Hidden REST API

**Discovery:** WG-Gesucht has an undocumented HAL+JSON REST API.

**Detail endpoint (works from httpx, no auth):**
```
GET https://www.wg-gesucht.de/api/offers/{offer_id}
Accept: application/json
```

Returns 100+ fields including:
- `offer_title`, `postcode`, `street`, `district_custom`
- `rent_costs` (Kaltmiete), `utility_costs` (Nebenkosten), `total_costs` (Warmmiete), `bond_costs` (Kaution)
- `property_size`, `number_of_rooms`, `floor_level`, `available_from_date`, `available_to_date`
- Full amenity booleans: `balcony`, `elevator`, `garden`, `washing_machine`, `furnished`, etc.
- Internet: `internet_dsl`, `internet_wlan`, `internet_fiber_optic`
- Flatmate info: `flatshare_inhabitants_total`, `flatmates_aged_from/to`, `searching_for_gender`
- Full free text descriptions

**Listing ID discovery (solved via sitemap):**

The search HTML is Cloudflare-protected, but the sitemap is fully accessible:
```
GET https://www.wg-gesucht.de/sitemaps/offer_detail_views/offer_details_DE.xml.gz
```

Returns gzipped XML with **44,658 listing URLs** across all of Germany. Filtering by city name in URL (e.g. `in-Berlin`) yields **9,405 Berlin listings**.

**Complete pipeline (no auth, no browser):**
1. Fetch sitemap → extract listing IDs filtered by city
2. Call `/api/offers/{id}` for each → full structured data

**Search endpoint:** `/api/offers` and `/api/offers/search` exist (400 not 404) but required params are unknown. Not needed since sitemap approach works.

## Immowelt — No Viable API

**Architecture:** Micro-frontend (UFRN) with server-side rendering. No client-side API calls for listing data.
- `__UFRN_LIFECYCLE_SERVERREQUEST__` contains search model (distributionTypes, estateTypes, placeIds)
- BFF endpoints (`/serp-bff/`, `/search-mfe-bff/`) only serve analytics and place hierarchy, not listings
- All listing data rendered server-side into HTML DOM
- Fetching the search URL with `Accept: application/json` still returns HTML

**Conclusion:** Would require Playwright (headless browser) — not viable for our use case. Deprioritized.

## Running the Tests

```bash
# ImmoScout24 — mobile API
python3 backend/apps/home/tests/test_immoscout24.py

# Kleinanzeigen — SSR HTML
python3 backend/apps/home/tests/test_kleinanzeigen.py

# WG-Gesucht — HTML + detail API
python3 backend/apps/home/tests/test_wg_gesucht.py

# Immowelt — SSR probe (will show JS-rendered)
python3 backend/apps/home/tests/test_immowelt.py
```

## Next Steps

1. Build unified `Listing` data model mapping all 3 providers
2. Design `home:search` parent embed + `listing` child embed
3. Implement Home app backend with provider adapters
4. Revisit Immowelt later if needed (3 providers give excellent coverage)
