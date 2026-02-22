# Events app architecture

> Not yet implemented. Idea stage.

## Feature Ideas

### Location-Based and Path-Based Event Search

**Idea:** Enable searching for events based on:

- **Near Location(s):** Find events near one or multiple specified locations
- **Along Travel Path:** Find events along a travel route/path the user is taking

**Considerations:**

- Integration with Maps functionality for route/path input
- Could leverage Travel app data for journey planning
- Spatial queries for event providers that support location data
- UI/UX for defining travel paths and search radius
- Cross-app integration: Events + Maps (+ Travel)

## Providers

### Meetup

**Official API:** Yes (GraphQL API — updated Feb 2025, endpoint: `https://api.meetup.com/gql-ext`)

**Pricing (as of Feb 2026):**

- **API access requires Meetup Pro** — the paid organizer subscription tier
- Meetup was acquired by **Bending Spoons** in 2023, which tripled Pro pricing with <30 days notice (mid-2024)
- Pro pricing has become increasingly expensive; many organizer communities have abandoned the platform as a result
- **There is no free API tier.** A free Meetup member account does not grant API access.

**API Capabilities:**

- **Event Management:** Create, publish, and edit events within groups you manage
- **Group Management:** Access group information, members, and settings
- **RSVP Management:** Access and manage event RSVPs and attendee data (including emails on Pro)
- **Event Search (Pro Network only):** `eventsSearch` query within a `proNetwork` — scoped to groups in YOUR Pro network, NOT a global public event search
- **Get single event by ID:** `event(id: "...")` — works without Pro scoping, returns public event data

**Critical Limitation — No Global Event Discovery:**

- The API does NOT provide a way to search all public Meetup events by keyword, city, or topic for arbitrary users
- `eventsSearch` is scoped to your own Pro Network's groups only
- Global event discovery is only available through the Meetup.com website itself, not the API

**Requirements:**

- **Subscription:** Meetup Pro subscription required for API access
- **Authentication:** OAuth 2.0 (Bearer token in Authorization header)
- **Rate Limit:** 500 points per 60 seconds

**Platform Health Warning:**

- Significant organizer exodus ongoing since 2024 price hikes
- Many groups migrating to Luma, Heylo, or self-hosted alternatives
- Platform activity declining; reliability as a comprehensive event source is questionable long-term

**Documentation:** [Meetup GraphQL API](https://www.meetup.com/graphql/)

### Eventbrite

**Official API:** Yes (REST API v3)

**API Capabilities:**

- **Event Management:** Create, update, and delete events
- **Ticketing:** Set up ticket types, pricing, and availability
- **Attendee Management:** Access attendee information and manage registrations
- **Event Search:** Search for public events based on various criteria
- **User Management:** Access and manage user profiles
- **Venue Management:** Manage venue details for events

**Requirements:**

- **API Key:** Generate API key through Eventbrite account settings
- **Authentication:** API key authentication required

**Limitations:**

- **Rate Limits:** API implements rate limiting
- **Terms:** Eventbrite reserves the right to change, suspend, or discontinue API features

**Documentation:** [Eventbrite API Documentation](https://www.eventbrite.com/platform/api-keys/)

### Luma

**Official API:** Yes (REST, base URL: `https://public-api.luma.com`)

**Pricing:**

- **Requires Luma Plus** paid subscription — free accounts cannot generate API keys
- Not suitable for event discovery integration

**API Capabilities:**

- **Event Management:** Create and manage events on your own calendar
- **Guest Management:** Send invitations, manage registrations, handle waitlists
- **Calendar Listing:** List events managed by your calendar (`GET /v1/calendar/list-events`)

**Critical Limitation — No Global Event Discovery:**

- The API is entirely **organizer-scoped**: it only returns events your own Luma calendar manages
- There is no endpoint to search or discover public events across all of Luma
- Luma does have a public web UI for browsing events by city (e.g., lu.ma/berlin), but this is not exposed via API

**Requirements:**

- **Subscription:** Active Luma Plus subscription required
- **API Key:** Generated from Luma dashboard, passed as `x-luma-api-key` header

**Verdict:** Not useful for OpenMates event discovery. Organizer tools only.

**Documentation:** [Luma API Documentation](https://docs.luma.com/reference/getting-started-with-your-api)

### rausgegangen.de

**Official API:** No

**Integration Method:** Web scraping required

**Capabilities:**

- **Event Discovery:** Scrape events from Berlin nightlife website
- **Event Details:** Extract event information, dates, venues, descriptions

**Limitations:**

- **No Official API:** Requires web scraping implementation
- **Rate Limiting:** Must implement respectful scraping practices
- **Data Structure:** Website structure may change, requiring maintenance

**Technical Considerations:**

- Implement proper rate limiting and respectful scraping
- Handle dynamic content loading (JavaScript-rendered content)
- Monitor for website structure changes

### smokesignal

**Official API:** No

**Integration Method:** Web scraping required

**Capabilities:**

- **Event Discovery:** Scrape events from Berlin events website
- **Event Details:** Extract event information, dates, venues, descriptions

**Limitations:**

- **No Official API:** Requires web scraping implementation
- **Rate Limiting:** Must implement respectful scraping practices
- **Data Structure:** Website structure may change, requiring maintenance

**Technical Considerations:**

- Implement proper rate limiting and respectful scraping
- Handle dynamic content loading (JavaScript-rendered content)
- Monitor for website structure changes

### Siegessäule

**Official API:** No

**Integration Method:** Web scraping required

**Capabilities:**

- **Event Discovery:** Scrape LGBTQ+ events from Berlin magazine website
- **Event Details:** Extract event information, dates, venues, descriptions

**Limitations:**

- **No Official API:** Requires web scraping implementation
- **Rate Limiting:** Must implement respectful scraping practices
- **Data Structure:** Website structure may change, requiring maintenance

**Technical Considerations:**

- Implement proper rate limiting and respectful scraping
- Handle dynamic content loading (JavaScript-rendered content)
- Monitor for website structure changes

### Major League Hacking (MLH)

**Official API:** No publicly documented API

**Integration Method:** Web scraping or potential partnership API access

**Capabilities:**

- **Hackathon Discovery:** Access to global hackathon events
- **Event Details:** Extract hackathon information including dates, locations (in-person/virtual), themes
- **Registration Information:** Links to hackathon registration pages
- **Event Categories:** Filter by season, location, event type

**Limitations:**

- **No Public API:** Requires web scraping implementation or partnership agreement
- **Rate Limiting:** Must implement respectful scraping practices
- **Data Structure:** Website structure may change, requiring maintenance
- **Geographic Coverage:** Primarily North America and Europe focused

**Technical Considerations:**

- Implement proper rate limiting and respectful scraping
- Handle dynamic content loading (JavaScript-rendered content)
- Monitor for website structure changes
- Consider reaching out to MLH for official API access or partnership

**Alternative Providers:**

- **Devpost:** Platform for hosting hackathons with searchable event listings
- **Hackathon.com:** Aggregator of hackathon events worldwide
- **MLH Season Pages:** MLH organizes hackathons by season with structured event listings

**Documentation:** [MLH Events](https://mlh.io/seasons/2025/events)

### FOSS.events

**Official API:** Yes

**API Capabilities:**

- **Event Discovery:** Search for free and open-source software (FOSS) related events
- **Event Details:** Access event information including dates, times, locations, descriptions
- **Event Categories:** Filter by event type, geography, and FOSS topics
- **Calendar Integration:** Export event data in standard formats

**Requirements:**

- **API Access:** Available for public use (check documentation for authentication requirements)
- **Rate Limits:** Respect rate limiting policies for API requests

**Limitations:**

- **Geographic Focus:** Primarily focused on FOSS community events globally
- **Event Categories:** Limited to FOSS-related events and conferences

**Technical Considerations:**

- Integrate with other event providers for comprehensive event coverage
- Consider geo-filtering for location-based event discovery
- May need to handle specialized event tags related to FOSS topics

**Documentation:** [FOSS.events](https://foss.events/)

### Berliner Philharmoniker

**Official API:** No

**Integration Method:** API reverse engineering required

**Capabilities:**

- **Concert Discovery:** Access to Berliner Philharmoniker concert calendar
- **Event Details:** Extract concert information including dates, times, conductors, soloists, program details
- **Ticket Information:** Links to ticketing system for event registration
- **Concert Archive:** Historical concert data available

**Technical Details:**

- **Website:** https://www.berliner-philharmoniker.de/konzerte/kalender/
- **Technology Stack:** TYPO3 CMS-based website with dynamic content loading
- **Data Format:** JSON API endpoints likely available (requires reverse engineering via network inspection)
- **Example Event URLs:** `/konzerte/kalender/{event_id}/` structure used for individual concerts

**Limitations:**

- **No Public API:** Requires reverse engineering network requests to identify API endpoints
- **Rate Limiting:** Must implement respectful rate limiting practices
- **Language:** Content primarily in German
- **Dynamic Content:** Calendar uses JavaScript-based filtering and pagination

**Technical Considerations:**

- Inspect network requests in browser DevTools to identify API endpoints
- Likely uses AJAX/Fetch calls for calendar data pagination
- May require analyzing search/filter functionality to understand query parameters
- Concert data includes: date, time, location (Philharmonie Berlin), conductor, soloists, program, ticket availability
- Consider implementing caching due to event schedule stability

**Alternative Approaches:**

- Monitor HTML structure for calendar changes
- Implement web scraping as fallback if API approach becomes difficult
- Contact Berliner Philharmoniker for official API access or partnership
