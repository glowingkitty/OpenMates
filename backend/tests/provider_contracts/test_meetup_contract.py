# backend/tests/provider_contracts/test_meetup_contract.py
#
# Daily contract probe for Meetup (events app).
# TODO: assert the GraphQL search endpoint used in
#       backend/apps/events/providers/meetup.py still returns event nodes
#       with id, title, dateTime, venue, and that no schema fields were
#       renamed upstream.

import pytest


@pytest.mark.provider_contract
@pytest.mark.skip(reason="TODO: port backend/apps/events/providers/meetup.py probes into this contract test")
async def test_meetup_search_contract() -> None:
    raise NotImplementedError
