"""Assistant-created Project: the resumed turn shows an activated focus card and clients persist the focus.

Contract: docs/plans/cloud-project-development/contracts/project-create-request.md
(sections 5 and 6). Covers the one-shot created record, the ``focus_mode_activated``
publication with the bound default focus id, the activation embed fields, its
gates and ownership recheck, and that the card leads the resumed answer.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.tests.test_main_processor_invalid_tool_calls import (  # fixture import activates it here
    _repository_google_provider_catalogue,  # noqa: F401 - autouse provider catalogue fixture
    _run_mocked_protocol_guard_main_processor,
)
from backend.tests.test_project_create_request import CREATED, FOCUS, PROJECT, REQUEST, _Cache, _report

pytest_plugins = ["backend.tests.test_async_skill_continuation"]

RECORD = {"request_id": REQUEST, "user_id": "owner", "chat_id": "chat", "message_id": "turn", "team_id": None,
          "project_id": PROJECT, "focus_id": FOCUS, "name": "Recipe Manager"}
BINDING = {"project_id": PROJECT, "team_id": None, "focus_id": FOCUS}


def _continuation(**overrides):
    values = dict(
        user_id="owner", user_id_hash="owner-hash", chat_id="chat", message_id="turn",
        original_user_message_id="turn", team_id=None, is_async_skill_continuation=True,
        async_skill_task_id=REQUEST, is_incognito=False, is_external=False,
        client_capabilities=["project_file_jobs", "project_create_requests"],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _created_cache(record=RECORD):
    from backend.core.api.app.services.project_create_request_service import ProjectCreateRequestService
    return _Cache({ProjectCreateRequestService.created_key("owner", REQUEST): dict(record)})


async def _card(monkeypatch, request, binding=BINDING, cache=None):
    from backend.apps.ai.processing import project_focus_orchestration as orchestration
    from backend.core.api.app.services import embed_service

    embed = AsyncMock(return_value={"embed_id": "card", "embed_reference": "{\"type\":\"focus_mode_activation\"}"})
    monkeypatch.setattr(embed_service.EmbedService, "create_focus_mode_activation_embed", embed)
    cache = cache or _created_cache()
    reference = await orchestration.created_project_activation_reference(
        task_id="task", request_data=request, active_project_focus=binding, cache_service=cache,
        directus_service=None, encryption_service=None, user_vault_key_id="vault", log_prefix="test",
    )
    return reference, embed, cache


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
async def test_created_report_publishes_bound_focus_and_records_card_before_resuming(
        monkeypatch, async_skill_continuation):
    from backend.core.api.app.services.project_create_request_service import ProjectCreateRequestService
    order = []
    publish = AsyncMock(side_effect=lambda *_: order.append("publish"))
    dispatch, sent, cache, _ = await _report(monkeypatch, async_skill_continuation, CREATED, publish=publish,
                                             on_dispatch=lambda: order.append("dispatch"))
    assert sent["type"] == "project_create_confirmed"
    assert order == ["publish", "dispatch"]
    channel, message = publish.await_args.args
    assert channel == "user_cache_events:owner"
    # The bare default focus id: what the binding, /focus/current and the client persist.
    assert json.loads(message) == {"event_type": "focus_mode_activated",
                                   "payload": {"chat_id": "chat", "focus_id": FOCUS}}
    record = cache.values[ProjectCreateRequestService.created_key("owner", REQUEST)]
    assert record == RECORD


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.parametrize("payload,variant", [
    ({"chat_id": "chat", "request_id": REQUEST, "status": "undone"}, {}),
    ({"chat_id": "chat", "request_id": REQUEST, "status": "failed"}, {}),
    (CREATED, {"focus_project": "44444444-4444-4444-8444-444444444444"}),
])
async def test_no_activation_without_a_verified_created_project(monkeypatch, async_skill_continuation,
                                                                 payload, variant):
    from backend.core.api.app.services.project_create_request_service import ProjectCreateRequestService
    publish = AsyncMock()
    _, _, cache, _ = await _report(monkeypatch, async_skill_continuation, payload, publish=publish, **variant)
    publish.assert_not_awaited()
    assert ProjectCreateRequestService.created_key("owner", REQUEST) not in cache.values


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
async def test_resumed_turn_card_is_an_activated_project_focus_with_creation_fields(monkeypatch):
    reference, embed, cache = await _card(monkeypatch, _continuation())
    assert reference == "{\"type\":\"focus_mode_activation\"}"
    kwargs = embed.await_args.kwargs
    assert kwargs["focus_id"] == f"project-{PROJECT}" and kwargs["app_id"] == "projects"
    assert kwargs["focus_mode_name"] == "Work on Recipe Manager"
    assert kwargs["chat_id"] == "chat" and kwargs["message_id"] == "turn"
    assert kwargs["extra_fields"] == {"project_created": True, "project_id": PROJECT,
                                      "project_focus_id": FOCUS, "project_name": "Recipe Manager"}
    assert cache.values == {}, "the card record is consumed once"
    again, embed, _ = await _card(monkeypatch, _continuation(), cache=cache)
    assert again is None
    embed.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.parametrize("overrides", [
    {"is_async_skill_continuation": False},
    {"async_skill_task_id": "33333333-3333-4333-8333-333333333333"},
    {"is_incognito": True},
    {"is_external": True},
    {"client_capabilities": ["project_file_jobs"]},
])
async def test_card_gates_keep_the_record_untouched(monkeypatch, overrides):
    reference, embed, cache = await _card(monkeypatch, _continuation(**overrides))
    assert reference is None
    embed.assert_not_awaited()
    assert cache.values, "a gated turn never consumes the record"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
@pytest.mark.parametrize("binding,request_overrides", [
    (None, {}),
    ({**BINDING, "project_id": "44444444-4444-4444-8444-444444444444"}, {}),
    ({**BINDING, "focus_id": "55555555-5555-4555-8555-555555555555"}, {}),
    ({**BINDING, "team_id": "team"}, {}),
    (BINDING, {"chat_id": "other"}),
    (BINDING, {"original_user_message_id": "later-turn"}),
])
async def test_undone_or_rebound_focus_shows_no_card(monkeypatch, binding, request_overrides):
    reference, embed, _ = await _card(monkeypatch, _continuation(**request_overrides), binding=binding)
    assert reference is None
    embed.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
async def test_embed_extra_fields_extend_but_never_replace_core_fields():
    from backend.core.api.app.services.embed_service import EmbedService
    encryption = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("cipher", None)))
    service = EmbedService(cache_service=None, directus_service=None, encryption_service=encryption)
    service.send_embed_data_to_client = AsyncMock()
    service._schedule_embed_persistence_fallback = lambda *_: None
    result = await service.create_focus_mode_activation_embed(
        focus_id=f"project-{PROJECT}", app_id="projects", focus_mode_name="Work on Recipe Manager",
        chat_id="chat", message_id="turn", user_id="owner", user_id_hash="hash", user_vault_key_id="vault",
        extra_fields={"project_created": True, "project_id": PROJECT, "focus_id": "spoofed", "type": "x"},
    )
    reference = json.loads(result["embed_reference"])
    assert reference["type"] == "focus_mode_activation" and reference["focus_id"] == f"project-{PROJECT}"
    assert reference["project_created"] is True and reference["project_id"] == PROJECT
    from toon_format import decode
    content = decode(service.send_embed_data_to_client.await_args.kwargs["content_toon"])
    assert content["status"] == "activated" and content["project_created"] is True
    assert content["focus_id"] == f"project-{PROJECT}"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
async def test_created_project_card_leads_the_resumed_answer(monkeypatch):
    from backend.apps.ai.processing import project_focus_orchestration as orchestration
    card = AsyncMock(return_value="{\"type\":\"focus_mode_activation\",\"embed_id\":\"card\"}")
    monkeypatch.setattr(orchestration, "created_project_activation_reference", card)
    output, _ = await _run_mocked_protocol_guard_main_processor(monkeypatch, [["Here is your recipe app."]])
    text = [chunk for chunk in output if isinstance(chunk, str)]
    assert text[0] == "```json\n{\"type\":\"focus_mode_activation\",\"embed_id\":\"card\"}\n```\n\n"
    assert "Here is your recipe app." in "".join(text[1:])
    card.assert_awaited_once()
