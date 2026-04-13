# backend/tests/provider_contracts/test_wg_gesucht_contract.py
#
# Daily contract probe for WG-Gesucht (backend/apps/home/providers/wg_gesucht.py).
#
# Two-stage skill: (1) scrape search HTML for data-id offer IDs, then
# (2) fetch /api/offers/{id} for structured JSON per offer.  Both stages
# are probed.
#
# What this catches:
#   * The /wg-zimmer-in-Berlin.8.0.1.0.html search page no longer inlining
#     offers (would kill the data-id regex and yield zero results).
#   * /api/offers/{id} HAL+JSON envelope renaming the offer_id / offer_title
#     / rent_costs / property_size fields the skill reads.
#   * Berlin city id 8 being rotated (would break the whole search URL).

from __future__ import annotations

import re

import httpx
import pytest

WG_GESUCHT_BASE = "https://www.wg-gesucht.de"
BERLIN_WG_URL = f"{WG_GESUCHT_BASE}/wg-zimmer-in-Berlin.8.0.1.0.html"
OFFER_DETAIL_URL_TEMPLATE = f"{WG_GESUCHT_BASE}/api/offers/{{offer_id}}"


@pytest.mark.provider_contract
async def test_wg_gesucht_berlin_search_html_has_offer_ids(
    browser_headers: dict[str, str],
) -> None:
    headers = {
        **browser_headers,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=headers
    ) as client:
        resp = await client.get(BERLIN_WG_URL)
        if resp.status_code in (403, 429):
            pytest.skip(
                f"WG-Gesucht returned HTTP {resp.status_code} — transient IP block"
            )
        assert resp.status_code == 200, (
            f"WG-Gesucht search HTTP {resp.status_code}"
        )
        offer_ids = re.findall(r'data-id="(\d{5,})"', resp.text)
        assert offer_ids, (
            "data-id attributes missing from WG-Gesucht HTML — "
            "offer id extraction would return zero rows"
        )
        assert len(set(offer_ids)) >= 5, (
            f"WG-Gesucht Berlin WG search only returned "
            f"{len(set(offer_ids))} unique offers — expected 5+"
        )


@pytest.mark.provider_contract
async def test_wg_gesucht_offer_detail_api_shape(
    browser_headers: dict[str, str],
) -> None:
    """Fetches one real offer_id from the search page, then hits the
    /api/offers/{id} detail endpoint and asserts the field names the skill
    reads."""
    headers = {
        **browser_headers,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=headers
    ) as client:
        search = await client.get(BERLIN_WG_URL)
        if search.status_code in (403, 429):
            pytest.skip(
                f"WG-Gesucht returned HTTP {search.status_code} — transient IP block"
            )
        assert search.status_code == 200
        offer_ids = re.findall(r'data-id="(\d{5,})"', search.text)
        assert offer_ids, "no offer ids to probe"

        api_headers = {
            **browser_headers,
            "Accept": "application/json",
        }
        # Try up to 3 offers — occasional listings 404 between scrape + fetch.
        last_status = 0
        detail: dict = {}
        for offer_id in offer_ids[:3]:
            detail_resp = await client.get(
                OFFER_DETAIL_URL_TEMPLATE.format(offer_id=offer_id),
                headers=api_headers,
            )
            last_status = detail_resp.status_code
            if last_status == 200:
                detail = detail_resp.json()
                break
        assert detail, (
            f"WG-Gesucht /api/offers/{{id}} kept failing (last HTTP {last_status})"
        )
        assert detail.get("offer_id"), "offer_id missing"
        assert detail.get("offer_title"), "offer_title missing"
        # rent_costs is the cold rent the skill reads. property_size is the m².
        assert "rent_costs" in detail, "rent_costs field removed"
        assert "property_size" in detail, "property_size field removed"
        assert "number_of_rooms" in detail, "number_of_rooms field removed"
