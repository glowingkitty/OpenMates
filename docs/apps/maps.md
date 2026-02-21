# Maps app architecture

> This file about the app called "Maps", which can be used by asking the digital team mates in a chat and later also via the OpenMates API. This file is NOT about the OpenMates web app, that allow users to access OpenMates via their web browser.

The maps app allows for searching places, finding locations, getting place details, and more.

## Skills

### Search

Searches for places using the Google Places API (New) Text Search endpoint.

- **Provider**: Google Maps Platform (Places API)
- **Endpoint**: `places:searchText`
- **Cost**: 40 credits per search request (Enterprise + Atmosphere SKU tier)
- **Maximum results per request**: 20 places
- **Pricing**: $0.032 USD per request (we charge 40 credits to cover currency conversion and small buffer)
- **Note**: Enterprise and Enterprise + Atmosphere SKU both cost $0.032, so we include all available fields at no extra cost!

**Features:**
- Supports multiple search queries in a single call (processed in parallel, up to 5 requests)
- Returns comprehensive place information including:
  - **Basic Info**: Display name, formatted address, location (latitude/longitude), place types, place ID
  - **Ratings**: Rating (1.0-5.0), user rating count
  - **Contact**: Website URI, phone number (international format preferred, national as fallback)
  - **Pricing**: Price level (0-4), price range
  - **Hours**: Opening hours as weekday descriptions array, `open_now` status, and `next_close_time` (all flattened to root)
  - **Business Status**: Operational status (OPERATIONAL, CLOSED_TEMPORARILY, etc.)
  - **Descriptions**: Editorial summary (description), AI-powered generative summary (only if not empty)
- **Note**: Reviews are NOT included by default as they significantly increase response size. Consider creating a separate skill for fetching reviews for a specific place.
- Supports optional filters:
  - `pageSize`: Number of results (1-20, default: 20)
  - `languageCode`: Language for results (ISO 639-1, e.g., 'en', 'es', 'fr')
  - `locationBias`: Prioritize results near a specific area (circle or rectangle)
  - `includedType`: Filter by place type (e.g., 'restaurant', 'museum')
  - `minRating`: Minimum rating filter (0.0 to 5.0)
  - `openNow`: Return only places currently open

**Data Fields Returned:**
- **Basic Information (Pro/Enterprise tier):**
  - `places.displayName` - Place name
  - `places.formattedAddress` - Full formatted address
  - `places.location` - Latitude/longitude coordinates
  - `places.types` - Array of place types
  - `places.id` - Place ID
  - `places.businessStatus` - Operational status
  
- **Ratings (Enterprise tier):**
  - `places.rating` - Rating from 1.0 to 5.0
  - `places.userRatingCount` - Total number of ratings
  
- **Contact Information (Enterprise tier):**
  - `places.websiteUri` - Website URL
  - `phone_number` - Single phone number field (international format preferred, national as fallback)
  
- **Pricing Information (Enterprise tier):**
  - `places.priceLevel` - Price level (0=free, 4=very expensive)
  - `places.priceRange` - Price range details
  
- **Opening Hours (Enterprise tier):**
  - `opening_hours` - Array of weekday descriptions (e.g., ["Monday: 11:30 AM – 10:00 PM", "Tuesday: 11:30 AM – 10:00 PM", ...])
    - Extracted from currentOpeningHours.weekdayDescriptions (preferred) or regularOpeningHours.weekdayDescriptions (fallback)
    - Human-readable text format that's perfect for LLM inference
  - `open_now` - Boolean indicating if place is currently open (flattened to root level for easy access)
  - `next_close_time` - ISO timestamp of next closing time (e.g., "2025-11-27T21:00:00Z")
    - Extracted from currentOpeningHours.nextCloseTime
  
- **Descriptions (Enterprise + Atmosphere tier):**
  - `places.editorialSummary` - Editorial description of the place
  - `places.generativeSummary` - AI-powered place summary (only included if not empty)
  
- **Reviews:**
  - Reviews are NOT included by default as they significantly increase response size
  - Consider creating a separate skill (e.g., "Get Place Reviews") for fetching reviews for a specific place
  - This would allow users to request reviews only when needed, keeping search results lean

**Note**: We use Enterprise + Atmosphere SKU tier fields. Since Enterprise and Enterprise + Atmosphere both cost $0.032 USD per request, we include all available fields (descriptions, summaries, etc.) at no extra cost! The cost is $0.032 USD per request regardless of how many results are returned (up to 20 per request).

**Architecture:**
- Executes directly in FastAPI route handler (not via Celery)
- Direct async execution for low latency
- Non-blocking I/O operations
- No content sanitization required (Google Places API data is trusted)

**Follow-up Suggestions:**
- "Show me more places nearby"
- "Filter by rating"
- "Get directions to this place"

## Settings and Memories

### Favorite Places

Stores user's favorite places for quick access.

**Schema:**
- `place_id`: Google Places API place ID (required)
- `name`: Place name (required)
- `address`: Formatted address
- `location`: Location object with latitude/longitude
- `added_date`: Unix timestamp when added to favorites

**Stage**: Planning (not yet implemented)

## Provider Configuration

**Google Maps Platform (Places API)**
- Provider ID: `google_maps`
- API Base URL: `https://places.googleapis.com/v1`
- API Key: Stored in Vault at `kv/data/providers/google_maps/api_key`
- Environment Variable: `SECRET__GOOGLE_MAPS__API_KEY`

**Rate Limits:**
- Default: 100 requests per 100 seconds per user
- Can be increased with higher-tier Google Maps Platform plans

**Pricing:**
- User-facing: 40 credits per search request
- Cost to us: $0.032 USD per request (Enterprise + Atmosphere SKU)
- Break-even: 32 credits (we charge 40 for small buffer)
- Note: Enterprise and Enterprise + Atmosphere SKU both cost the same, so we include all fields!

## Future Enhancements

Potential future skills and features:
- **Get Place Reviews**: Fetch user reviews for a specific place (using Place Details endpoint with reviews field)
  - This would be a separate skill to avoid bloating search results
  - Users can request reviews only when needed
  - Uses Enterprise + Atmosphere SKU tier (same cost as search)
- **Get Directions**: Route planning between places
- **Place Details**: Detailed information about a specific place
- **Nearby Search**: Find places within a specified radius
- **Place Photos**: Access to place photos (available in Pro SKU tier)
- **Busyness Data Integration (BestTime.app)**: Add foot traffic/busyness data to place search results
  - **Provider**: BestTime.app API
  - **API Documentation**: https://documentation.besttime.app
  - **Implementation Approach**: Add optional `check_busyness` parameter to search skill (defaults to `False`)
    - When enabled, fetches busyness forecasts for each place in parallel
    - Returns busyness data (peak hours, quiet hours, busyness percentages per hour) in place objects
  - **Pricing Considerations**:
    - **Cost per venue**: 2 credits for new forecast (must assume worst case)
      - Basic - Metered: $0.08 per venue ($0.04 per credit)
      - Pro - Metered: $0.018 per venue ($0.009 per credit)
    - **Minimum monthly costs**:
      - Basic - Metered: $29/month minimum (even if usage is lower)
      - Pro - Metered: $99/month minimum (even if usage is lower)
    - **Package plans** (unlimited API calls):
      - Basic - Package: $299/month (up to 1M unique venues/month)
      - Pro - Package: $399/month (up to 100k unique venues/month)
  - **Cost Example for 20 Places**:
    - 20 venues × 2 credits = 40 credits
    - Basic - Metered: 40 × $0.04 = $1.60 (but $29/month minimum applies)
    - Pro - Metered: 40 × $0.009 = $0.36 (but $99/month minimum applies)
  - **Important Notes**:
    - No batch API support - requires one request per venue (20 parallel requests for 20 places)
    - Cannot check if venue exists before forecasting (would cost 1 credit to query, then 2 to forecast = 3 total)
    - Must plan for 2 credits per venue (worst case scenario)
    - Forecasts can be cached and reused for weeks (query existing forecasts costs only 1 credit)
  - **Optimization Strategy**:
    - Cache `venue_id`s after first forecast
    - Query cached venues (1 credit) instead of re-forecasting (2 credits)
    - Only implement when usage volume justifies minimum monthly costs
  - **Status**: Planned for future implementation (not yet implemented due to cost considerations)

