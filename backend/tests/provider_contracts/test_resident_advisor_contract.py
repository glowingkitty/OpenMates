# backend/tests/provider_contracts/test_resident_advisor_contract.py
#
# Daily contract probe for Resident Advisor
# (backend/apps/events/providers/resident_advisor.py).
#
# What this catches:
#   * ra.co/graphql endpoint removed / CORS tightened
#   * eventListings GraphQL operation renamed or filters argument changed
#   * data[].event.{id,title,date,venue.name,venue.area.name} field drift
#   * Berlin area id 34 rotated (would break the whole city-lookup path)

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

RA_GRAPHQL_URL = "https://ra.co/graphql"
BERLIN_AREA_ID = 34


EVENT_LISTINGS_QUERY = """
query GET_EVENT_LISTINGS($filters: FilterInputDtoInput, $pageSize: Int) {
  eventListings(filters: $filters, pageSize: $pageSize) {
    data {
      event {
        id
        title
        date
        venue {
          name
          area { name }
          location { latitude longitude }
        }
      }
    }
    totalResults
  }
}
"""


@pytest.mark.provider_contract
async def test_ra_berlin_eventlistings_returns_events(
    browser_headers: dict[str, str],
) -> None:
    headers = {
        **browser_headers,
        "Content-Type": "application/json",
        "Origin": "https://ra.co",
        "Referer": "https://ra.co/events",
    }
    start = date.today()
    end = start + timedelta(days=14)
    payload = {
        "operationName": "GET_EVENT_LISTINGS",
        "query": EVENT_LISTINGS_QUERY,
        "variables": {
            "filters": {
                "areas": {"eq": BERLIN_AREA_ID},
                "listingDate": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                },
            },
            "pageSize": 10,
        },
    }
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        resp = await client.post(RA_GRAPHQL_URL, json=payload)
        assert resp.status_code == 200, (
            f"RA GraphQL HTTP {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        listings = ((body.get("data") or {}).get("eventListings") or {})
        items = listings.get("data") or []
        assert items, (
            f"RA eventListings returned zero items. "
            f"Full response: {str(body)[:300]}"
        )
        event = (items[0] or {}).get("event") or {}
        assert event.get("id"), "event.id missing"
        assert event.get("title"), "event.title missing"
        assert event.get("date"), "event.date missing"
        venue = event.get("venue") or {}
        assert venue.get("name"), "event.venue.name missing"
        area = venue.get("area") or {}
        assert area.get("name"), "event.venue.area.name missing"
