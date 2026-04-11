# backend/tests/provider_contracts/test_kleinanzeigen_contract.py
#
# Daily contract probe for Kleinanzeigen (shopping app).
# TODO: scrape the public search page and assert the HTML structure still
#       yields the listing attributes the skill extracts (title, price,
#       location, link, thumbnail).  Use the Webshare proxy — Kleinanzeigen
#       rate-limits datacenter egress.

import pytest


@pytest.mark.provider_contract
@pytest.mark.skip(reason="TODO: implement Kleinanzeigen contract probe (HTML selectors + price parsing)")
async def test_kleinanzeigen_search_contract() -> None:
    raise NotImplementedError
