# backend/tests/provider_contracts/test_meetup_contract.py
#
# Daily contract probe for Meetup (backend/apps/events/providers/meetup.py).
#
# What this catches:
#   * www.meetup.com/gql2 endpoint removed or moved
#   * eventSearch GraphQL op renamed or signature changed
#   * data.eventSearch.edges[].node.{id,title,dateTime,venue.city} field drift

from __future__ import annotations

import httpx
import pytest

MEETUP_GRAPHQL_URL = "https://www.meetup.com/gql2"
BERLIN_LAT = 52.52
BERLIN_LON = 13.405


EVENT_SEARCH_QUERY = """
query eventSearch(
    $filter: EventSearchFilter!,
    $sort: KeywordSort,
    $first: Int,
    $after: String
) {
    eventSearch(filter: $filter, sort: $sort, first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        totalCount
        edges {
            node {
                id
                title
                dateTime
                eventUrl
                venue { name city country }
                group { id name }
            }
        }
    }
}
"""


@pytest.mark.provider_contract
async def test_meetup_berlin_search_returns_events(
    browser_headers: dict[str, str],
) -> None:
    headers = {
        **browser_headers,
        "Content-Type": "application/json",
        "apollographql-client-name": "nextjs-web",
        "Referer": "https://www.meetup.com/find/",
        "Origin": "https://www.meetup.com",
    }
    payload = {
        "operationName": "eventSearch",
        "query": EVENT_SEARCH_QUERY,
        "variables": {
            "filter": {
                "query": "python",
                "lat": BERLIN_LAT,
                "lon": BERLIN_LON,
                "radius": 25,
                "doConsolidateEvents": False,
            },
            "sort": {"sortField": "RELEVANCE"},
            "first": 20,
        },
    }
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        resp = await client.post(MEETUP_GRAPHQL_URL, json=payload)
        assert resp.status_code == 200, (
            f"Meetup GraphQL HTTP {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        search = (data.get("data") or {}).get("eventSearch") or {}
        edges = search.get("edges") or []
        assert edges, (
            f"Meetup eventSearch returned zero edges. "
            f"Full response: {str(data)[:300]}"
        )
        node = (edges[0] or {}).get("node") or {}
        assert node.get("id"), "node.id missing"
        assert node.get("title"), "node.title missing"
        assert node.get("dateTime"), "node.dateTime missing"
        # Venue is optional for online events; at least one event in the top
        # 10 must carry a city name for the skill's flow to work.
        assert any(
            ((e.get("node") or {}).get("venue") or {}).get("city")
            for e in edges[:10]
        ), "No event in the top 10 has venue.city"
