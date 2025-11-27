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

**Official API:** Yes (GraphQL API v3)

**API Capabilities:**
- **Event Management:** Create, update, and manage events within groups
- **Group Management:** Access group information, members, and settings
- **Member Management:** Access member profiles and memberships
- **Event Search:** Search for public events and groups based on various criteria
- **RSVP Management:** Manage event RSVPs and attendee information

**Requirements:**
- **Subscription:** Meetup Pro subscription required
- **Registration:** Must register for API access and agree to license terms
- **Authentication:** OAuth 2.0 authentication required

**Limitations:**
- **Rate Limits:** API implements rate limiting for performance
- **Commercial Use:** Meetup reserves the right to modify or terminate access if commercial interests are undermined

**Documentation:** [Meetup API Documentation](https://www.meetup.com/api/)

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

**Official API:** Yes

**API Capabilities:**
- **Event Management:** Create and manage events with details (dates, locations, ticket types)
- **Guest Management:** Send invitations, manage registrations, handle waitlists
- **Analytics:** Retrieve attendance data and event insights
- **Calendar Synchronization:** Sync calendar data with external systems

**Requirements:**
- **Subscription:** Active Luma Plus subscription required
- **API Key:** Generate API key from Luma dashboard (calendar-specific)
- **Authentication:** Include API key in `x-luma-api-key` header

**Limitations:**
- **Search Functionality:** No support for searching events (organizer-focused only)
- **Rate Limits:** API implements rate limiting for performance

**Documentation:** [Luma API Documentation](https://docs.lu.ma/)

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