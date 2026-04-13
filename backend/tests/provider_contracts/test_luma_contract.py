# backend/tests/provider_contracts/test_luma_contract.py
#
# Daily contract probe for Luma (backend/apps/events/providers/luma.py).
#
# What this catches:
#   * api2.luma.com/discover/get-paginated-events returning a non-200
#   * entries[] response shape change (event.api_id, name, start_at,
#     geo_address_info, coordinate, calendar, hosts — all read by the skill)
#   * Cloudflare anti-bot putting the endpoint behind a challenge page

from __future__ import annotations

import httpx
import pytest

LUMA_SEARCH_URL = "https://api2.luma.com/discover/get-paginated-events"
# Berlin's Luma place API id — stable, used by the skill's CITY_COORDS
# reference list.  If this id rotates the whole city lookup breaks, so it's
# worth probing directly.
BERLIN_PLACE_ID = "discplace-gCfX0s3E9Hgo3rG"


@pytest.mark.provider_contract
async def test_luma_berlin_search_returns_entries(
    browser_headers: dict[str, str],
) -> None:
    headers = {
        **browser_headers,
        "Origin": "https://luma.com",
        "Referer": "https://luma.com/discover",
    }
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        resp = await client.get(
            LUMA_SEARCH_URL,
            params={
                "discover_place_api_id": BERLIN_PLACE_ID,
                "pagination_limit": 20,
                "query": "tech",
            },
        )
        assert resp.status_code == 200, (
            f"Luma discover HTTP {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        entries = data.get("entries") or []
        assert entries, "Luma returned zero entries for 'tech' in Berlin"

        # Inspect the first entry for the exact fields the skill reads.
        sample = entries[0]
        event = sample.get("event") or {}
        assert event.get("api_id"), "event.api_id missing"
        assert event.get("name"), "event.name missing"
        assert event.get("start_at"), "event.start_at missing"
        # geo_address_info is optional per event (online events have none)
        # but at least ONE of the first 10 entries must have it, otherwise
        # the whole city-lookup flow is dead.
        assert any(
            (e.get("event") or {}).get("geo_address_info")
            for e in entries[:10]
        ), "No entry in the top 10 has geo_address_info.city"
