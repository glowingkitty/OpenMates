"""A queued steer joins only at a preflighted, exact-revision boundary."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.queued_steering import (
    consume_safe_queued_steer, reconcile_queued_revision_quarantine,
)
from backend.apps.ai.skills.ask_skill import AskSkillRequest


# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision
def test_epoch_one_edit_rebinds_exact_message_and_mode_commitment(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment
    from backend.core.api.app.routes.handlers.websocket_handlers.revise_queued_message_handler import _amended_recovery_inference_request

    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    original = {
        "message": {"message_id": "queued", "content": "Before", "encrypted_content": "old-cipher"},
        "message_history": [{"role": "user", "message_id": "queued", "content": "Before"}],
        "queue_mode": "follow_up",
    }
    member = {"message_id": "queued", "recovery_inference_request": original,
              "recovery_inference_commitment": build_inference_commitment(original)}
    amended, old_hmac, next_hmac = _amended_recovery_inference_request(
        member, queue_mode="steer", content="After", encrypted_content="new-cipher",
        encrypted_pii_mappings=None,
    )
    assert old_hmac == member["recovery_inference_commitment"]
    assert next_hmac == build_inference_commitment(amended) != old_hmac
    assert amended["message"]["content"] == "After"
    assert amended["message_history"][0]["content"] == "After"
    assert original["message"]["content"] == "Before"
    with pytest.raises(ValueError, match="changed"):
        _amended_recovery_inference_request(
            {**member, "recovery_inference_commitment": "0" * 64},
            queue_mode="follow_up", content=None, encrypted_content=None,
            encrypted_pii_mappings=None,
        )


def _request(message_id="first", content="First question"):
    return AskSkillRequest(
        chat_id="chat", message_id=message_id, user_id="owner", user_id_hash="owner-hash",
        message_history=[{"role": "user", "message_id": message_id,
                          "content": content, "created_at": 1}],
        current_user_content=content,
    )


def _preflight(*, safe=True, model="model", mate="mate", rules=None,
               workflows=None, memories=None):
    return SimpleNamespace(
        can_proceed=safe, routing_only=False,
        pending_project_focus_id=None, pending_project_catalog_id=None,
        pending_project_specialist=None,
        selected_main_llm_model_id=model, selected_mate_id=mate,
        relevant_rules=rules or [], relevant_workflows=workflows or [],
        relevant_focus_modes=[], load_app_settings_and_memories=memories or [],
        relevant_app_skills=[], requires_advice_disclaimer=None,
        filtered_cn_models=False,
    )


class _Cache:
    def __init__(self, row):
        self.row = row
        self.events = []
        self.claimed = False
        self.revised = False
        self.marked = False

    async def peek_steer_queued_message(self, chat_id, user_id, *, exclude_ids):
        return None if self.row["member"]["message_id"] in exclude_ids else self.row

    async def get_queued_message_member(self, chat_id, user_id, message_id):
        return self.row

    @asynccontextmanager
    async def queued_message_edit_lock(self, chat_id):
        yield SimpleNamespace(local=SimpleNamespace(token=b"lock"))

    async def claim_steer_queued_message(self, *args, **kwargs):
        assert self.marked or self.row["member"].get("is_incognito")
        self.claim_kwargs = kwargs
        self.claimed = True
        return True

    async def revise_queued_message_member(self, *args, **kwargs):
        self.revised = True
        return "updated"

    async def replace_sync_message_revision(self, *args, **kwargs):
        return True

    async def begin_queued_message_revision_quarantine(self, *args, **kwargs):
        return json.dumps({"nonce": "stage-test"})

    async def clear_queued_message_revision_quarantine(self, *args, **kwargs):
        return True

    async def mark_sync_message_processing(self, *args, **kwargs):
        return True

    async def publish_event(self, channel, event):
        self.events.append(event)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_compatible_steer_claims_exact_revision_after_preflight(monkeypatch):
    from backend.apps.ai.processing import preprocessor

    queued = _request("queued", "Use the result to compare both options")
    queued.queue_mode = "steer"
    member = queued.model_dump()
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    directus = SimpleNamespace(chat=SimpleNamespace())

    async def mark_started(*args, **kwargs):
        assert cache.events == []
        cache.marked = True
        return {"status": "started", "messages_v": 8}

    directus.chat.mark_queued_message_started = mark_started
    preflight = AsyncMock(return_value=_preflight())
    monkeypatch.setattr(preprocessor, "handle_preprocessing", preflight)
    excluded = set()
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=excluded,
    )

    assert result.message_id == "queued"
    assert result.content == "Use the result to compare both options"
    assert cache.claimed
    assert excluded == {"queued"}
    assert [event["event_for_client"] for event in cache.events] == ["queued_message_steered"]
    preflight.assert_awaited_once()


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_formatting_steer_keeps_active_model_and_mate_when_auto_routing_drifts(monkeypatch):
    from backend.apps.ai.processing import preprocessor

    queued = _request("queued", "Make the current answer shorter")
    queued.queue_mode = "steer"
    member = queued.model_dump()
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    async def mark_started(*args, **kwargs):
        cache.marked = True
        return {"status": "started", "messages_v": 8}
    directus = SimpleNamespace(chat=SimpleNamespace(
        mark_queued_message_started=mark_started,
    ))
    # A short formatting request naturally classifies differently from a
    # complex active Travel response. It still uses the active model/Mate.
    monkeypatch.setattr(preprocessor, "handle_preprocessing", AsyncMock(return_value=_preflight(
        model="simple-model", mate="george",
    )))
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=set(),
    )
    assert result.content == "Make the current answer shorter"
    assert cache.claimed
    assert not any(event["event_for_client"] == "queued_message_steer_deferred"
                   for event in cache.events)


@pytest.mark.anyio
@pytest.mark.parametrize("override", ["@ai-model:other-model", "@mate:george"])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_explicit_model_or_mate_change_defers_to_new_turn(monkeypatch, override):
    queued = _request("queued", f"Make it shorter {override}")
    queued.queue_mode = "steer"
    member = queued.model_dump()
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    directus = SimpleNamespace(chat=SimpleNamespace(
        revise_queued_message_ciphertext=AsyncMock(return_value={
            "status": "staged", "stage_token": "stage-test",
            "previous_encrypted_content": "ciphertext",
            "previous_encrypted_pii_mappings": None,
        }),
        commit_queued_message_revision=AsyncMock(return_value={
            "status": "updated", "messages_v": 9,
        }),
    ))
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=set(),
    )
    assert result is None
    assert not cache.claimed
    assert cache.events[-1]["event_for_client"] == "queued_message_steer_deferred"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_fresh_private_snapshot_defers_but_existing_snapshot_can_steer(monkeypatch):
    from backend.apps.ai.processing import preprocessor

    queued = _request("queued", "Summarize with the same rules")
    queued.queue_mode = "steer"
    member = queued.model_dump()
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    directus = SimpleNamespace(chat=SimpleNamespace(
        revise_queued_message_ciphertext=AsyncMock(return_value={
            "status": "staged", "stage_token": "stage-test",
            "previous_encrypted_content": "ciphertext",
            "previous_encrypted_pii_mappings": None,
        }),
        commit_queued_message_revision=AsyncMock(return_value={
            "status": "updated", "messages_v": 9,
        }),
        mark_queued_message_started=AsyncMock(return_value={"status": "started", "messages_v": 10}),
    ))
    selected = _preflight(rules=[{"id": "new-rule", "revision": 2}])
    monkeypatch.setattr(preprocessor, "handle_preprocessing", AsyncMock(return_value=selected))
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=set(),
    )
    assert result is None
    assert not cache.claimed
    assert cache.events[-1]["event_for_client"] == "queued_message_steer_deferred"

    # An exact already-authorized revision may be reused within this response.
    cache = _Cache(row)
    async def mark_started(*args, **kwargs):
        cache.marked = True
        return {"status": "started", "messages_v": 10}
    directus.chat.mark_queued_message_started = mark_started
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=selected,
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=set(),
    )
    assert result.message_id == "queued"
    assert cache.claimed


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_epoch_one_steer_consumes_existing_preflight_before_context_injection(monkeypatch):
    from backend.apps.ai.processing import preprocessor
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment

    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    queued = _request("queued", "Compare the completed result")
    queued.queue_mode = "steer"
    member = queued.model_dump()
    original = {"message": {"message_id": "queued", "content": queued.current_user_content},
                "queue_mode": "steer"}
    member.update({
        "recovery_task_id": "queued-task", "recovery_preflight_id": "queued-preflight",
        "recovery_inference_request": original,
        "recovery_inference_commitment": build_inference_commitment(original),
    })
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    directus = SimpleNamespace(chat=SimpleNamespace())
    receipts = []

    async def mark_started(*args, **kwargs):
        assert kwargs["recovery_preflight_id"] == "queued-preflight"
        assert kwargs["recovery_task_id"] == "queued-task"
        assert args[-1] == "steer"
        receipts.append("consumed")
        cache.marked = True
        return {"status": "started", "messages_v": 9}

    directus.chat.mark_queued_message_started = mark_started
    monkeypatch.setattr(preprocessor, "handle_preprocessing", AsyncMock(return_value=_preflight()))
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=set(),
    )
    assert result.content == "Compare the completed result"
    assert receipts == ["consumed"]
    assert cache.claimed


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_failed_active_run_pauses_consumed_steer_by_same_task_receipt(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task, async_skill_continuation

    cache = SimpleNamespace(
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
        publish_event=AsyncMock(),
    )
    pause = AsyncMock(return_value={
        "status": "paused", "messages_v": 10,
        "messages": [{"message_id": "steered", "queue_revision": 2,
                      "queue_mode": "steer", "pause_reason": "dispatch_failed"}],
    })
    directus = SimpleNamespace(chat=SimpleNamespace(pause_consumed_steers_for_task=pause))
    monkeypatch.setattr(ask_skill_task, "_cleanup_processing_embeds_on_task_failure",
                        AsyncMock(return_value=0))
    monkeypatch.setattr(async_skill_continuation, "dispatch_deferred_async_skill_continuations",
                        AsyncMock())
    await ask_skill_task._cleanup_on_task_failure(
        task_id="active-task", chat_id="chat", message_id="first",
        user_id="owner", user_id_hash="owner-hash", user_vault_key_id="vault",
        error_message="current run failed after consuming steer",
        cache_service=cache, directus_service=directus, request_data=_request(),
    )
    pause.assert_awaited_once_with("chat", "owner", "active-task", hashed_team_id=None)
    event = next(call.args[1] for call in cache.publish_event.await_args_list
                 if call.args[1].get("event_for_client") == "queued_handoff_paused")
    assert event["event_for_client"] == "queued_handoff_paused"
    assert event["payload"]["message_id"] == "steered"
    assert event["payload"]["reason_code"] == "dispatch_failed"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_failed_incognito_run_pauses_consumed_volatile_steer(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task, async_skill_continuation

    cache = SimpleNamespace(
        get_active_ai_task=AsyncMock(return_value="active-task"),
        get_consumed_volatile_steers=AsyncMock(return_value=[{
            "user_id": "owner", "user_id_hash": "owner-hash", "message_id": "steered",
        }]),
        clear_consumed_volatile_steers=AsyncMock(),
        lease_queued_message_prefix=AsyncMock(return_value=None),
        complete_active_ai_task_if_queue_empty=AsyncMock(return_value=1),
        clear_active_ai_task_if_matches=AsyncMock(),
        publish_event=AsyncMock(),
    )
    monkeypatch.setattr(ask_skill_task, "_cleanup_processing_embeds_on_task_failure",
                        AsyncMock(return_value=0))
    monkeypatch.setattr(async_skill_continuation, "dispatch_deferred_async_skill_continuations",
                        AsyncMock())
    request = _request()
    request.is_incognito = True
    await ask_skill_task._cleanup_on_task_failure(
        task_id="active-task", chat_id="chat", message_id="first",
        user_id="owner", user_id_hash="owner-hash", user_vault_key_id="vault",
        error_message="current run failed after consuming volatile steer",
        cache_service=cache, request_data=request,
    )
    paused = next(call.args[1] for call in cache.publish_event.await_args_list
                  if call.args[1].get("event_for_client") == "queued_handoff_paused")
    assert paused["payload"]["message_id"] == "steered"
    assert paused["payload"]["reason_code"] == "volatile_predecessor_failed"
    cache.clear_consumed_volatile_steers.assert_awaited_once_with("chat", "active-task")
    cache.clear_active_ai_task_if_matches.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_incognito_steer_claim_writes_task_bound_failure_receipt(monkeypatch):
    from backend.apps.ai.processing import preprocessor

    queued = _request("steered", "Use the completed result")
    queued.is_incognito = True
    queued.queue_mode = "steer"
    member = queued.model_dump()
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    request = _request()
    request.is_incognito = True
    monkeypatch.setattr(preprocessor, "handle_preprocessing", AsyncMock(return_value=_preflight()))
    result = await consume_safe_queued_steer(
        task_id="active-task", request=request, current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=SimpleNamespace(chat=SimpleNamespace()),
        encryption=object(), secrets=object(), discovered_apps={}, excluded_ids=set(),
    )
    assert result.message_id == "steered"
    assert cache.claim_kwargs["volatile_receipt"] == {
        "user_id": "owner", "user_id_hash": "owner-hash", "message_id": "steered",
    }


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.steering.safe-boundary
async def test_rejected_steer_remains_ordinary_queued_followup(monkeypatch):
    from backend.apps.ai.processing import preprocessor

    queued = _request("queued", "Switch to a gated Project")
    queued.queue_mode = "steer"
    member = queued.model_dump()
    row = {"member": member, "raw": json.dumps(member, separators=(",", ":"))}
    cache = _Cache(row)
    directus = SimpleNamespace(chat=SimpleNamespace(
        revise_queued_message_ciphertext=AsyncMock(return_value={
            "status": "staged", "stage_token": "stage-test",
            "previous_encrypted_content": "ciphertext",
            "previous_encrypted_pii_mappings": None,
        }),
        commit_queued_message_revision=AsyncMock(return_value={
            "status": "updated", "messages_v": 9,
        }),
    ))
    monkeypatch.setattr(preprocessor, "handle_preprocessing", AsyncMock(return_value=_preflight(safe=False)))
    result = await consume_safe_queued_steer(
        task_id="active-task", request=_request(), current_preprocessing=_preflight(),
        base_instructions={}, skill_config_dict={"enable_auto_model_selection": False},
        cache=cache, directus=directus, encryption=object(), secrets=object(),
        discovered_apps={}, excluded_ids=set(),
    )

    assert result is None
    assert not cache.claimed
    assert cache.revised
    assert cache.events[-1]["payload"] == {
        "chat_id": "chat", "message_id": "queued", "queue_mode": "follow_up",
        "queue_revision": 2, "reason_code": "preflight_rejected",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("queue_revision,expected_operation", [(1, "abort"), (2, "commit")])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision
async def test_staged_edit_crash_reconciles_exact_queue_revision_and_sync_cache(
    queue_revision, expected_operation,
):
    row = {"member": {"message_id": "queued", "queue_revision": queue_revision}, "raw": "member"}
    cache = _Cache(row)
    marker = json.dumps({
        "nonce": "stage-nonce", "user_id": "owner", "message_id": "queued",
        "expected_revision": 1, "hashed_team_id": None,
    })
    cache.get_queued_message_revision_quarantine = AsyncMock(return_value=marker)
    cache.clear_queued_message_revision_quarantine = AsyncMock(return_value=True)
    cache.delete_sync_messages_history = AsyncMock()
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_queued_revision_state=AsyncMock(return_value={
            "status": "found", "queue_revision": 1,
            "pending_revision": 2, "pending_token": "stage-nonce",
        }),
        restore_queued_message_ciphertext=AsyncMock(return_value={"status": "restored"}),
        commit_queued_message_revision=AsyncMock(return_value={"status": "updated"}),
    ))
    assert await reconcile_queued_revision_quarantine(cache, directus, "chat")
    cache.clear_queued_message_revision_quarantine.assert_awaited_once_with("chat", marker)
    if expected_operation == "abort":
        directus.chat.restore_queued_message_ciphertext.assert_awaited_once()
        directus.chat.commit_queued_message_revision.assert_not_awaited()
        cache.delete_sync_messages_history.assert_not_awaited()
    else:
        directus.chat.commit_queued_message_revision.assert_awaited_once()
        directus.chat.restore_queued_message_ciphertext.assert_not_awaited()
        cache.delete_sync_messages_history.assert_awaited_once_with("owner", "chat")


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision,chat-queued-followups.access.scoped
async def test_incognito_edit_ack_stays_on_origin_session_without_ciphertext():
    from backend.core.api.app.routes.handlers.websocket_handlers.revise_queued_message_handler import (
        handle_revise_queued_message,
    )
    queued = _request("volatile", "Original")
    queued.is_incognito = True
    row = {"member": queued.model_dump(), "raw": json.dumps(queued.model_dump())}
    cache = _Cache(row)
    cache.get_queued_message_revision_quarantine = AsyncMock(return_value=None)
    cache.get_active_ai_task = AsyncMock(return_value="active-task")
    manager = SimpleNamespace(
        send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock(),
    )
    await handle_revise_queued_message(
        manager=manager, cache_service=cache,
        directus_service=SimpleNamespace(), encryption_service=SimpleNamespace(),
        user_id="owner", device_fingerprint_hash="origin-device",
        payload={"chat_id": "chat", "message_id": "volatile",
                 "expected_revision": 1, "content": "Edited while running",
                 "client_request_id": "edit-one"},
    )
    assert cache.revised
    manager.broadcast_to_user.assert_not_awaited()
    event, owner_id, device_id = manager.send_personal_message.await_args.args
    assert (owner_id, device_id) == ("owner", "origin-device")
    assert event["type"] == "queued_message_updated"
    assert event["payload"]["queue_revision"] == 2
    assert "encrypted_content" not in event["payload"]
