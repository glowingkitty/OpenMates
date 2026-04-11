# backend/tests/provider_contracts/test_luma_contract.py
#
# Daily contract probe for Luma (events app).
# TODO: implement probes for the Luma GraphQL endpoints we call in
#       backend/apps/events/providers/luma.py — minimally:
#   * search query (city → event list) returns non-empty edges
#   * each event has the fields the skill reads (id, title, start_at, venue)

import pytest


@pytest.mark.provider_contract
@pytest.mark.skip(reason="TODO: port backend/apps/events/providers/luma.py probes into this contract test")
async def test_luma_search_contract() -> None:
    raise NotImplementedError
