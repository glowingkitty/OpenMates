"""Pre-consent Focus discovery exposes only current, owned item metadata."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.project_focus_routing import validated_focus_candidates_for_project
from backend.core.api.app.services.project_recommendation_service import project_item_revision

PROJECT = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"


def _item(**overrides):
    return {"project_item_id": ITEM, "item_type": "embed", "target_id_hash": "opaque",
            "encrypted_metadata": "cipher", "updated_at": 4, "deleted_target_state": None,
            **overrides}


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_preconsent_focus_catalog_requires_current_owned_item_revision_and_strips_private_fields():
    item = _item()
    directus = SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[item])))
    offered = {"item_id": ITEM, "revision": project_item_revision(item), "title": "  Service  debugging ",
               "description": " Review   failures ", "when_to_use": " When services fail ",
               "document": "PRIVATE INSTRUCTIONS", "display_path": ".openmates/focuses/private/SKILL.md"}
    result = await validated_focus_candidates_for_project(
        {"project_id": PROJECT, "focuses": [offered]}, directus_service=directus,
        user_id="owner", team_id="team",
    )
    directus.project.list_items.assert_awaited_once_with(PROJECT, "owner", team_id="team")
    assert result == [{"focus_id": f"project-focus:{PROJECT}:{ITEM}", "item_id": ITEM,
                       "revision": offered["revision"], "title": "Service debugging",
                       "description": "Review failures", "when_to_use": "When services fail"}]
    assert "PRIVATE INSTRUCTIONS" not in str(result)
    assert "display_path" not in str(result)


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
@pytest.mark.asyncio
async def test_preconsent_focus_catalog_rejects_stale_deleted_other_type_and_forged_ids():
    item = _item()
    directus = SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[item])))
    offered = {"item_id": ITEM, "revision": project_item_revision(item),
               "title": "Debugging", "description": "Failures"}
    async def validate(row, metadata=offered):
        directus.project.list_items.return_value = [row]
        return await validated_focus_candidates_for_project(
            {"project_id": PROJECT, "focuses": [metadata]}, directus_service=directus,
            user_id="owner", team_id=None,
        )
    assert await validate(_item(updated_at=5)) == []
    assert await validate(_item(deleted_target_state="deleted")) == []
    assert await validate(_item(item_type="file")) == []
    assert await validate(item, {**offered, "item_id": "33333333-3333-4333-8333-333333333333"}) == []
    assert await validate(item, {**offered, "revision": "a" * 64}) == []


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
@pytest.mark.asyncio
async def test_preconsent_focus_catalog_is_bounded_and_deduplicated():
    item = _item()
    directus = SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[item])))
    offered = {"item_id": ITEM, "revision": project_item_revision(item),
               "title": "T" * 250, "description": "D" * 900, "when_to_use": "W" * 900}
    result = await validated_focus_candidates_for_project(
        {"project_id": PROJECT, "focuses": [offered] * 30}, directus_service=directus,
        user_id="owner", team_id=None,
    )
    assert len(result) == 1
    assert len(result[0]["title"]) == 180
    assert len(result[0]["description"]) == 640
    assert len(result[0]["when_to_use"]) == 640
