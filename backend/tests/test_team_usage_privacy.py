"""Team billing views retain charges without linkable chat identifiers."""

import csv
import io

import pytest

from backend.core.api.app.services.team_billing_service import TeamBillingService, team_usage_csv_values
from backend.core.api.app.services.team_data_portability_service import TeamDataPortabilityService


# contract-test: direct surface=rest_api assertions=teams.direct-chat.participant-isolation,teams.chat-billing.team-credit-boundary
@pytest.mark.anyio
async def test_team_usage_json_csv_and_portability_hide_resource_hash_preserve_credits():
    chat_hash = "a" * 64
    usage_row = {
        "id": "usage-1", "event_id": "ai-ask:task-1:main", "hashed_team_id": "team-hash",
        "actor_user_hash": "member-hash", "workspace_type": "chat", "object_id_hash": chat_hash,
        "credit_amount": 17, "created_at": 123,
    }

    class FakeTeam:
        async def require_team_role(self, team_id, user_id, roles):
            assert team_id == "team-1"
            assert user_id == "admin-1"
            return {"role": "owner"}

    class FakeDirectus:
        team = FakeTeam()

        async def get_items(self, collection, params, **kwargs):
            assert collection == "team_usage_events"
            return [usage_row]

    directus = FakeDirectus()
    [listed] = await TeamBillingService(directus).list_usage("team-1", "admin-1")
    assert "object_id_hash" not in listed
    assert listed["credit_amount"] == 17
    assert listed["event_id"] == usage_row["event_id"]

    fields = ("created_at", "actor_user_hash", "workspace_type", "object_id_hash", "credit_amount", "event_id")
    output = io.StringIO()
    csv.writer(output).writerow(team_usage_csv_values(usage_row, fields))
    assert chat_hash not in output.getvalue()
    assert list(csv.reader(io.StringIO(output.getvalue())))[0][4] == "17"

    exported = TeamDataPortabilityService(directus)._redact_row(usage_row, collection="team_usage_events")
    assert "object_id_hash" not in exported
    assert exported["credit_amount"] == 17
