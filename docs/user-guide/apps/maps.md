---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-07-30
claims:
  - id: user-guide-apps-maps-source
    type: unit
    claim: The Maps app guide is grounded in the Maps app metadata.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-maps-source
---

# Maps

> Search for places, restaurants, businesses, and get location details.

## What It Does

The Maps app searches for places around the world and returns detailed information including ratings, opening hours, contact details, and descriptions.

**Available skills:**

- **Search** -- Find places by name, type, or description. Returns up to 20 results per search with detailed information. You can run multiple searches at once (up to 5 in parallel).

**What you get for each place:**

- Name and full address
- Rating and number of reviews
- Opening hours and whether it is currently open
- Website and phone number
- Price level
- A description of the place
- Source-labelled OpenStreetMap/Geoapify amenity details when available, such as air conditioning, internet access, wheelchair access, toilets, smoking, outdoor seating, diet, and payment hints
- Location on a map

## How to Use It

- Find restaurants: "Find Italian restaurants in Berlin with at least 4 stars"
- Search by type: "Show me pharmacies near Times Square that are open now"
- Compare options: "Find coffee shops and coworking spaces in Amsterdam"
- Get specific details: "Search for museums in Paris"
- Discover ruins: "Find ruins within 10 km of Potsdam, Germany"
- Find outdoor places: "Show viewpoints and picnic sites within 5 km of Dresden"
- Find facilities: "Find drinking water or toilets near Berlin Mitte"
- Find campsites: "Show campsites within 20 km of Freiburg, Germany"

These six discovery categories use OpenStreetMap via the existing Geoapify connection.
Give a city or region and country, or coordinates. The default radius is 10 km and
the maximum is 50 km. Combined categories match any of the selected types.
An ambiguous area needs a more specific name or coordinates. This searches mapped
ruins; it does not find every abandoned building or establish permission to enter.
Ratings, current opening hours and other unmapped facts remain unknown.

For a direct CLI search:

```sh
openmates apps maps search --input '{"requests":[{"query":"Ruins near Potsdam","categories":["ruins"],"area":{"name":"Potsdam, Germany","radiusMeters":10000},"pageSize":10}]}'
```

Discovery does not support the ordinary Google search rating, open-now, price or
review filters. Searches and area lookups are cached; when the shared Geoapify
allowance is unavailable, the search returns an explicit error. This uses the
existing provider account and keeps the existing OpenMates credit pricing.

## Screenshots

![Place search results](../../images/user-guide/apps/maps/previews/search/finished.jpg)

## Tips

- Results appear as interactive cards with a map view. Click any result to see it in fullscreen with more details.
- You can filter results by minimum rating, whether the place is currently open, and by place type.
- When you ask for amenities such as air conditioning, free Wi-Fi, or wheelchair access, OpenMates may use Geoapify's OpenStreetMap-backed data to verify those details. Missing OSM data is shown as unknown, not as proof that a place lacks the amenity.
- Your mate can search in different languages, so results will match the local language of the area you are searching.
- Searches can be biased toward a specific area if you provide coordinates or describe a location.

## Related

- [Events](./events.md) -- Find events happening at or near places
- [Travel](./travel.md) -- Plan travel to a destination
- [Shopping](./shopping.md) -- Search for products to buy
