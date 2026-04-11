# backend/tests/provider_contracts/test_immoscout24_contract.py
#
# Daily contract probe for ImmoScout24 (housing app).
# TODO: Immoscout24 ships a strong anti-bot layer; probe must go through
#       the Webshare proxy and assert the mobile API / HTML structure still
#       yields the fields the skill extracts.

import pytest


@pytest.mark.provider_contract
@pytest.mark.skip(reason="TODO: implement Immoscout24 contract probe (needs proxy + anti-bot header set)")
async def test_immoscout24_search_contract() -> None:
    raise NotImplementedError
