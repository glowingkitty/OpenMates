# backend/tests/provider_contracts/test_resident_advisor_contract.py
#
# Daily contract probe for Resident Advisor (events app).
# TODO: assert the undocumented GraphQL endpoint used in
#       backend/apps/events/providers/resident_advisor.py still returns
#       event nodes with the fields the skill reads.

import pytest


@pytest.mark.provider_contract
@pytest.mark.skip(reason="TODO: port backend/apps/events/providers/resident_advisor.py probes into this contract test")
async def test_resident_advisor_search_contract() -> None:
    raise NotImplementedError
