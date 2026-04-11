# backend/tests/provider_contracts/test_kleinanzeigen_contract.py
#
# Daily contract probe for Kleinanzeigen (backend/apps/home/providers/kleinanzeigen.py).
#
# What this catches:
#   * The /s-{category}/{city}/{code}{location} URL pattern being renamed
#     or redirected into a SPA that no longer inlines listings in HTML.
#   * The data-adid attribute being removed — our regex parser depends on
#     it for every listing row.
#   * The aditem-main--middle--price / aditem-main--top--left CSS hooks
#     rotating — if they're gone, price and address extraction both die.
#   * Kleinanzeigen deciding our worker IP deserves a hard 403 (we fetch
#     from the container egress, no proxy). The probe therefore tolerates
#     403 as a SKIP rather than a FAIL so transient IP blocks don't
#     create false alerts — but assertion on body shape is strict.

from __future__ import annotations

import re

import httpx
import pytest

KLEINANZEIGEN_URL = (
    "https://www.kleinanzeigen.de/s-wohnungen-mieten/berlin/c203l3331"
)


@pytest.mark.provider_contract
async def test_kleinanzeigen_berlin_rent_listing_shape(
    browser_headers: dict[str, str],
) -> None:
    headers = {
        **browser_headers,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.kleinanzeigen.de/",
    }
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=headers
    ) as client:
        resp = await client.get(KLEINANZEIGEN_URL)
        if resp.status_code in (403, 429):
            pytest.skip(
                f"Kleinanzeigen returned HTTP {resp.status_code} "
                "(anti-bot — transient IP block)"
            )
        assert resp.status_code == 200, (
            f"Kleinanzeigen listing HTTP {resp.status_code}"
        )
        html = resp.text
        ad_ids = re.findall(r'data-adid="(\d+)"', html)
        assert ad_ids, (
            "data-adid attributes missing from Kleinanzeigen HTML — "
            "listing parser would return zero rows."
        )
        assert len(ad_ids) >= 3, (
            f"Kleinanzeigen only returned {len(ad_ids)} listings — "
            "Berlin /s-wohnungen-mieten/ should always have 20+."
        )
        # CSS hooks our parser depends on.
        assert "aditem-main--middle--price" in html, (
            "aditem-main--middle--price class missing — price parser dies"
        )
        assert "aditem-main--top--left" in html, (
            "aditem-main--top--left class missing — address parser dies"
        )
