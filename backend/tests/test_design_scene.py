"""Validation and typed edits of the shared Design scene wire format."""

import json

import pytest
from pydantic import ValidationError

from backend.apps.design.scene import DesignEdits, DesignScene, parse_draft


def _scene() -> dict:
    return {
        "schemaVersion": 1,
        "title": "Open Studio Weekend",
        "pages": [{
            "id": "cover", "name": "Cover", "width": 640, "height": 480, "background": "#f4e9d6",
            "layers": [{
                "kind": "text", "id": "headline", "name": "Headline", "x": 48, "y": 43, "width": 544,
                "height": 120, "rotation": 0, "text": "Open Studio Weekend", "font": "Serif",
                "fontSize": 48, "weight": 700, "color": "#18314b",
            }],
        }],
    }


# contract-test: supporting surface=gui.web assertions=design-editor.assistant.route
def test_new_design_has_canonical_json_and_no_asset_lookup():
    original = _scene()
    scene = parse_draft(json.dumps(original), None)
    assert json.loads(scene.wire_json()) == original
    layer = original["pages"][0]["layers"][0]
    original["pages"][0]["layers"][0] = {
        key: layer[key] for key in ("id", "name", "x", "y", "width", "height", "rotation")
    } | {"kind": "image", "assetId": "e235e2bd-c404-42db-8ca5-1c091abb9228"}
    with pytest.raises(ValueError, match="private assets"):
        parse_draft(json.dumps(original), None)


# contract-test: supporting surface=gui.web assertions=design-editor.assistant.apply
def test_followup_updates_only_an_unlocked_existing_layer():
    original = DesignScene.model_validate(_scene())
    edit = {"kind": "update_layer", "pageId": "cover", "layerId": "headline",
            "changes": {"text": "Open Studio Saturday", "x": 62}}
    revised = parse_draft(json.dumps({"operations": [edit]}), original)
    assert revised.pages[0].layers[0].text == "Open Studio Saturday"
    assert revised.pages[0].layers[0].x == 62
    assert original.pages[0].layers[0].text == "Open Studio Weekend"
    with pytest.raises(ValueError, match="unlocked layer"):
        DesignEdits.model_validate({"operations": [{**edit, "layerId": "missing"}]}).apply(original)


# contract-test: supporting surface=gui.web assertions=design-editor.assistant.route
def test_unexpected_keys_and_excess_layers_are_refused():
    original = _scene()
    layers = original["pages"][0]["layers"]
    layers[0]["src"] = "https://example.invalid/asset"
    with pytest.raises(ValidationError):
        DesignScene.model_validate(original)
    del layers[0]["src"]
    layers.extend({**layers[0], "id": f"copy-{index}"} for index in range(250))
    with pytest.raises(ValidationError):
        DesignScene.model_validate(original)


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=design-editor.assistant.review
async def test_author_repairs_one_invalid_draft_and_fails_closed_without_review(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from backend.apps.design import scene_author
    from backend.apps.images.vector_author import VectorReview, VectorUsage

    meter = VectorUsage("author", "google/test-model", 1000, 600)
    policy = SimpleNamespace(
        author_routes=lambda *args, **kwargs: [SimpleNamespace(model_id="google/test-model")],
        stream_options=lambda route: {},
    )
    draft = AsyncMock(side_effect=[("{}", meter), (json.dumps(_scene()), meter)])
    review = AsyncMock(return_value=VectorReview(accepted=True, status="unavailable"))
    monkeypatch.setattr(scene_author, "_draft", draft)
    monkeypatch.setattr(scene_author, "review_preview", lambda scene: ("<svg/>", ()))
    monkeypatch.setattr(scene_author, "review_with_jev", review)

    result = await scene_author.author_design(
        task_id="test-design", brief="Make a flyer", exact_copy=("Open Studio Weekend",), policy=policy,
    )
    assert result.scene is None
    assert result.error == "design_review_unavailable"
    assert result.attempts == draft.await_count == 2
    assert review.await_count == 1
    assert "Correct the draft" in draft.await_args.kwargs["messages"][-1]["content"]


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=design-editor.assistant.review
async def test_one_visual_correction_can_be_reviewed_and_accepted(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from backend.apps.design import scene_author
    from backend.apps.images.vector_author import VectorReview, VectorUsage

    meter = VectorUsage("author", "google/test-model", 1000, 600)
    policy = SimpleNamespace(
        author_routes=lambda *args, **kwargs: [SimpleNamespace(model_id="google/test-model")],
        stream_options=lambda route: {},
    )
    draft = AsyncMock(return_value=(json.dumps(_scene()), meter))
    review = AsyncMock(side_effect=[
        VectorReview(accepted=False, status="rejected", feedback="Increase contrast."),
        VectorReview(accepted=True, status="accepted", input_tokens=40, output_tokens=20),
    ])
    monkeypatch.setattr(scene_author, "_draft", draft)
    monkeypatch.setattr(scene_author, "review_preview", lambda scene: ("<svg/>", ()))
    monkeypatch.setattr(scene_author, "review_with_jev", review)

    result = await scene_author.author_design(task_id="test-design", brief="Make a flyer", policy=policy)
    assert result.scene.title == "Open Studio Weekend"
    assert draft.await_count == review.await_count == 2
    assert "Increase contrast" in draft.await_args.kwargs["messages"][-1]["content"]
    assert [item.step for item in result.usage] == ["author", "author", "review"]


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=design-editor.assistant.apply
async def test_only_current_owned_design_is_allowed_as_the_revision_source():
    from hashlib import sha256
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from backend.apps.design.source import design_skill_arguments

    request = SimpleNamespace(
        user_id="owner", chat_id="personal-chat", team_id=None,
        is_incognito=False, is_anonymous=False, is_external=False,
        design_source={
            "embed_id": "e235e2bd-c404-42db-8ca5-1c091abb9228", "base_version": 3, "scene": _scene(),
        },
    )
    head = {
        "version_number": 3, "encryption_mode": "client", "app_id": "design", "skill_id": "document",
        "hashed_user_id": sha256(b"owner").hexdigest(), "hashed_chat_id": sha256(b"personal-chat").hexdigest(),
    }
    read = AsyncMock(return_value=head)
    directus = SimpleNamespace(embed=SimpleNamespace(get_sync_embed_by_id=read))
    allowed = await design_skill_arguments({"brief": "Move the headline"}, request, directus)
    assert allowed["revise"]
    assert allowed["_design_source"].base_version == 3
    head["version_number"] = 4
    stale = await design_skill_arguments({"brief": "Move the headline"}, request, directus)
    assert stale["revise"] and stale["_design_source"] is None
    head["version_number"] = 3
    head["hashed_chat_id"] = sha256(b"another chat").hexdigest()
    unowned = await design_skill_arguments({"brief": "Move the headline"}, request, directus)
    assert unowned["revise"] and unowned["_design_source"] is None


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=design-editor.assistant.route
async def test_design_requirements_and_exact_copy_stay_in_one_skill_call(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.apps.ai.processing import skill_executor

    execute = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(skill_executor, "execute_skill", execute)
    arguments = {
        "brief": "Make an editable flyer", "exact_copy": ["Open Studio", "Saturday 11:00"],
        "requirements": ["Readable date", "Indigo and cream"],
    }
    result = await skill_executor.execute_skill_with_multiple_requests("design", "author", arguments)
    assert result == [{"success": True}]
    assert execute.await_count == 1
    assert execute.await_args.args[2] == arguments


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=design-editor.assistant.apply
async def test_delivery_uses_the_existing_personal_root_identity_and_client_encryption():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import UUID

    from backend.apps.design.delivery import deliver_design

    publish = AsyncMock(return_value=True)
    result, reference = await deliver_design(
        {"success": True, "scene_json": json.dumps(_scene()), "credits_charged": 22},
        service=SimpleNamespace(send_embed_data_to_client=publish),
        chat_id="chat", message_id="message", user_id="owner", user_id_hash="owner-hash", task_id="task",
    )
    payload = publish.await_args.kwargs
    assert UUID(payload["embed_id"]).version == 4
    assert payload["encryption_mode"] == "client"
    assert payload["embed_type"] == "design-document"
    assert payload["app_id"] == "design" and payload["skill_id"] == "document"
    assert payload["version_number"] == 1
    assert "finished_cache_data" not in payload
    assert json.loads(reference)["embed_id"] == payload["embed_id"]
    assert result["credits_charged"] == 22 and "scene_json" not in result
