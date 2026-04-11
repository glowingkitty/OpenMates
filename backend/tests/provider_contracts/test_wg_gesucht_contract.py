# backend/tests/provider_contracts/test_wg_gesucht_contract.py
#
# Daily contract probe for WG-Gesucht (housing app).
# TODO: assert the search HTML structure still yields the listing fields
#       the skill extracts (title, rent, rooms, address, URL).

import pytest


@pytest.mark.provider_contract
@pytest.mark.skip(reason="TODO: implement WG-Gesucht contract probe (HTML selectors)")
async def test_wg_gesucht_search_contract() -> None:
    raise NotImplementedError
