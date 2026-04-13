# backend/tests/provider_contracts/test_immoscout24_contract.py
#
# Daily contract probe for Immoscout24 mobile API
# (backend/apps/home/providers/immoscout24.py).
#
# What this catches:
#   * api.mobile.immobilienscout24.de/search/list endpoint removed or
#     moved under a new version prefix.
#   * resultListItems[] wrapper / .item field-path change.
#   * item.attributes[] positional schema flip (the skill reads
#     attributes[0..2] as price/size/rooms — order is structural, not
#     labelled, so any upstream reorder silently breaks the output).
#   * titlePicture { full, preview } rename.
#   * The ImmoScout_27.12_26.2_._ mobile User-Agent being rejected.

from __future__ import annotations

import httpx
import pytest

IMMOSCOUT_MOBILE_API = "https://api.mobile.immobilienscout24.de/search/list"
IMMOSCOUT_USER_AGENT = "ImmoScout_27.12_26.2_._"


@pytest.mark.provider_contract
async def test_immoscout24_berlin_rent_search_shape() -> None:
    headers = {
        "User-Agent": IMMOSCOUT_USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {
        "searchType": "region",
        "realestatetype": "apartmentrent",
        "geocodes": "/de/berlin/berlin",
    }
    body = {"supportedResultListTypes": [], "userData": {}}
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        resp = await client.post(IMMOSCOUT_MOBILE_API, params=params, json=body)
        assert resp.status_code == 200, (
            f"Immoscout24 HTTP {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        items = data.get("resultListItems") or []
        assert items, "Immoscout24 returned zero resultListItems for Berlin rent"

        # Find the first EXPOSE_RESULT wrapper.
        expose = next(
            (i for i in items if i.get("type") == "EXPOSE_RESULT"),
            None,
        )
        assert expose is not None, (
            "No EXPOSE_RESULT wrapper in resultListItems — every item was a "
            "sponsored slot or header. resultListItems[].type field may have "
            "been renamed."
        )
        item = expose.get("item") or {}
        assert item.get("id"), "item.id missing"
        assert item.get("title"), "item.title missing"
        attributes = item.get("attributes") or []
        assert len(attributes) >= 3, (
            f"item.attributes has {len(attributes)} entries — skill reads "
            "[0]=price, [1]=size, [2]=rooms positionally."
        )
        assert (item.get("address") or {}).get("line"), (
            "item.address.line missing"
        )
        title_pic = item.get("titlePicture") or {}
        assert title_pic.get("full") or title_pic.get("preview"), (
            "item.titlePicture missing both .full and .preview"
        )
