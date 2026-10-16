"""Selected-only context loading stays behind fresh Project authority and revision."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from backend.core.api.app.services.project_context_selection_service import (
    ProjectContextCandidate, ProjectContextSelectionRequest, ProjectContextSelectionService,
)
from backend.core.api.app.services.project_recommendation_service import project_item_revision
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError
from backend.shared.providers.typesafe.models import NoulAnswer

PROJECT = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"


class BudgetCache:
    @property
    async def client(self):
        return SimpleNamespace(incr=AsyncMock(return_value=1), expire=AsyncMock())


def setup_selection():
    row = {"project_item_id": ITEM, "item_type": "embed", "updated_at": 1, "encrypted_metadata": "cipher"}
    directus = SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[row])))
    jev = SimpleNamespace(evaluate=AsyncMock(return_value=SimpleNamespace(answers={
        "candidate_0": NoulAnswer(type="noul", noul=0.9)})))
    service = ProjectContextSelectionService(directus=directus, cache=BudgetCache(), jev=jev)
    service.authorization.get_active_focus = AsyncMock(return_value={"project_id": PROJECT, "team_id": None,
                                                                    "activation_id": "accepted-base"})
    body = ProjectContextSelectionRequest(chat_id="chat", text="Debug the startup failure", candidates=[
        ProjectContextCandidate(kind="focus", id=UUID(ITEM), title="Debugging", revision=project_item_revision(row)),
    ])
    return row, service, jev, body


# contract-test: supporting surface=rest_api assertions=focus-modes.context-reselection,projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_metadata_selection_requires_accepted_project_and_excludes_foreign_items():
    _, service, jev, body = setup_selection()
    service.authorization.get_active_focus.return_value = None
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.select(user_id="user", project_id=PROJECT, team_id=None, body=body)
    jev.evaluate.assert_not_awaited()
    service.authorization.get_active_focus.return_value = {"project_id": PROJECT, "team_id": None, "activation_id": "accepted"}
    body.candidates[0].id = UUID("33333333-3333-4333-8333-333333333333")
    assert await service.select(user_id="user", project_id=PROJECT, team_id=None, body=body) == []
    jev.evaluate.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=focus-modes.context-reselection
@pytest.mark.asyncio
async def test_selected_identity_has_current_revision_and_no_full_private_content():
    _, service, jev, body = setup_selection()
    result = await service.select(user_id="user", project_id=PROJECT, team_id=None, body=body)
    assert result == [{"id": ITEM, "kind": "focus", "revision": body.candidates[0].revision}]
    assert "cipher" not in str(jev.evaluate.call_args)
    assert "document" not in jev.evaluate.call_args.kwargs["state"]["candidates"][0]


# contract-test: supporting surface=rest_api assertions=focus-modes.context-reselection,projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_revocation_or_revision_change_during_selection_discards_results():
    row, service, jev, body = setup_selection()
    service.authorization.get_active_focus.side_effect = [{"project_id": PROJECT, "team_id": None}, None]
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.select(user_id="user", project_id=PROJECT, team_id=None, body=body)
    service.authorization.get_active_focus.side_effect = None
    service.authorization.get_active_focus.return_value = {"project_id": PROJECT, "team_id": None}
    async def mutate(**_):
        row["encrypted_metadata"] = "new-cipher"
        return SimpleNamespace(answers={"candidate_0": NoulAnswer(type="noul", noul=1)})
    jev.evaluate.side_effect = mutate
    assert await service.select(user_id="user", project_id=PROJECT, team_id=None, body=body) == []
