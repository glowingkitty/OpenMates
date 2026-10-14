# contract-test-file: infrastructure
"""Compose natural consent, root policy and verifier dispatch without inference."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.tests.test_main_processor_invalid_tool_calls import (
    _run_mocked_protocol_guard_main_processor,
    private_focus_activation_context as _private_focus_activation_context,
)


private_focus_activation_context = _private_focus_activation_context


class _RootPrepared(Exception):
    """Stop the real activated request after its external root transaction."""


def _focus_catalog():
    return {"web": SimpleNamespace(skills=[], instructions=[], focuses=[SimpleNamespace(
        id="research", name_translation_key="research.name",
        description_translation_key="research.description", auto_activate_when_relevant=True,
        system_prompt="Delegate three independent research angles, then verify primary sources.",
        systemprompt_translation_key=None, phases=None,
    )])}


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=focus-modes.natural-request,focus-modes.full-instruction
async def test_natural_focus_defers_root_until_acceptance_then_waits_for_verifier(
    monkeypatch, private_focus_activation_context,
):
    from backend.apps.ai import sub_chat_orchestration
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.tasks import stream_consumer
    import fakeredis.aioredis

    roots, operations = {}, []
    stop_after_root = False

    class Transactions:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, payload):
            operations.append((operation, payload))
            root_id = payload["orchestration_id"]
            if operation == "create_root":
                # Existing roots intentionally never upgrade from legacy/null.
                roots.setdefault(root_id, {**payload,
                    "research_stage": "research" if payload["deep_research"] else None})
                if stop_after_root:
                    raise _RootPrepared
                return roots[root_id]
            root = roots[root_id]
            if operation == "claim_parent_continuation":
                assert root["research_stage"] == "research"
                return {"dispatch_required": True, "research_stage": "verification_due",
                    "root_chat_id": root["root_chat_id"], "root_turn_id": root["root_turn_id"],
                    "batch_id": payload["batch_id"], "research_batch_id": payload["batch_id"],
                    "continuation_task_id": "88888888-8888-4888-8888-888888888888",
                    "verifier_batch_id": "99999999-9999-4999-8999-999999999999",
                    "verifier_child_id": "77777777-7777-4777-8777-777777777777"}
            if operation == "prepare_batch":
                assert payload["is_continuation"] is True
                assert len(payload["children"]) == 1
                root["research_stage"] = "verification_running"
                return {}
            assert operation == "mark_parent_continuation_dispatched"
            return {}

    monkeypatch.setattr(sub_chat_orchestration, "SubChatOrchestrationService", Transactions)
    context = private_focus_activation_context
    request_fields = {"chat_id": "11111111-1111-4111-8111-111111111111",
        "message_id": "22222222-2222-4222-8222-222222222222", "root_user_message_id": None}
    output, calls = await _run_mocked_protocol_guard_main_processor(
        monkeypatch, [], cache_service=context.cache, directus_service=Mock(),
        user_vault_key_id="test-vault-key", discovered_apps_metadata=_focus_catalog(),
        request_overrides=request_fields,
        preprocessing_overrides={"relevant_focus_modes": ["web-research"], "enable_subchats": True},
    )
    assert calls == []
    assert any(isinstance(row, dict) and row.get("__awaiting_focus_mode_confirmation__") for row in output)
    pending = context.cache.store_pending_focus_activation.await_args.kwargs["context"]
    assert pending["focus_id"] == "web-research"
    assert pending["orchestration_id"] is None
    assert pending["root_chat_id"] is None and pending["root_turn_id"] is None
    assert roots == {}  # The bug created a permanent ordinary/null-stage root here.

    # Acceptance forwards the captured ancestry unchanged and adds active Focus.
    activated = {**request_fields, "active_focus_id": pending["focus_id"], "is_focus_mode_continuation": True,
        **{key: pending[key] for key in ("orchestration_id", "root_chat_id", "root_turn_id", "sub_chat_depth")}}
    stop_after_root = True
    with pytest.raises(_RootPrepared):
        await _run_mocked_protocol_guard_main_processor(
            monkeypatch, [], cache_service=context.cache, directus_service=Mock(),
            user_vault_key_id="test-vault-key", discovered_apps_metadata=_focus_catalog(),
            request_overrides=activated,
            preprocessing_overrides={"relevant_focus_modes": ["web-research"], "enable_subchats": True},
        )
    assert len(roots) == 1
    root = next(iter(roots.values()))
    assert root["deep_research"] is True and root["research_stage"] == "research"

    # Initial research completion follows the real continuation/prepare path;
    # broker and provider boundaries remain mocked, never invoked for a final.
    original = AskSkillRequest(chat_id=request_fields["chat_id"], message_id=request_fields["message_id"],
        user_id="user-1", user_id_hash="user-hash-1", active_focus_id="web-research",
        message_history=[{"role": "user", "content": "Investigate competing explanations.", "created_at": 1}],
        orchestration_id=root["orchestration_id"], root_chat_id=root["root_chat_id"], root_turn_id=root["root_turn_id"])
    children = [f"{n:08d}-3333-4333-8333-333333333333" for n in range(3)]
    initial = {"parent_task_id": "parent-task", "parent_request_data": original.model_dump(mode="json"),
        "pending_batch_id": "research-batch", "expected_sub_chat_ids": children, "completed": {child: {
            "summary": f"Independent angle {n} report.", "chat_id": child, "parent_id": original.chat_id,
            "owner_hash": original.user_id_hash, "root_chat_id": original.root_chat_id,
            "root_turn_id": original.root_turn_id, "orchestration_id": original.orchestration_id,
        } for n, child in enumerate(children)}}
    redis = fakeredis.aioredis.FakeRedis()
    class Cache:
        @property
        async def client(self):
            return redis
        async def get(self, key):
            value = await redis.get(key)
            return json.loads(value) if value is not None else None
        async def set(self, key, value, *, ttl):
            return await redis.setex(key, ttl, json.dumps(value))
        set_active_ai_task = AsyncMock()
    cache = Cache()
    await cache.set(stream_consumer._sub_chat_pending_key(original.chat_id), initial, ttl=86400)
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "unit-test-only-token")
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", Transactions)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", AsyncMock())
    verifier_dispatch = AsyncMock(return_value="verifier-task")
    monkeypatch.setattr(stream_consumer, "dispatch_sub_chat_task", verifier_dispatch)
    final_dispatch = Mock(side_effect=AssertionError("Final inference before verification"))
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", final_dispatch)
    result = await stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=cache,
        pending_context=initial, parent_chat_id=original.chat_id, durable_batch_id="research-batch", log_prefix="[natural]")
    assert result is False
    verifier_dispatch.assert_awaited_once()
    final_dispatch.assert_not_called()
    assert root["research_stage"] == "verification_running"
    assert (await cache.get(stream_consumer._sub_chat_pending_key(original.chat_id)))["expected_sub_chat_ids"] == [
        "77777777-7777-4777-8777-777777777777"]
    await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("relevant,extra", [([], {}), (["web-research"], {"is_external": True}),
    (["web-research"], {"is_focus_mode_continuation": True})])
# contract-test: supporting surface=cli assertions=focus-modes.natural-request
async def test_ordinary_subchat_routes_keep_eager_root_before_inference(
    monkeypatch, private_focus_activation_context, relevant, extra,
):
    from backend.apps.ai import sub_chat_orchestration
    prepared = []
    class Transactions:
        def __init__(self, _directus):
            pass
        async def execute(self, operation, payload):
            assert operation == "create_root"
            prepared.append(payload)
            raise _RootPrepared
    monkeypatch.setattr(sub_chat_orchestration, "SubChatOrchestrationService", Transactions)
    with pytest.raises(_RootPrepared):
        await _run_mocked_protocol_guard_main_processor(
            monkeypatch, [], cache_service=private_focus_activation_context.cache,
            directus_service=Mock(), user_vault_key_id="test-vault-key",
            discovered_apps_metadata=_focus_catalog(),
            request_overrides={"root_user_message_id": None, **extra},
            preprocessing_overrides={"enable_subchats": True, "relevant_focus_modes": relevant},
        )
    assert prepared[0]["deep_research"] is False
    private_focus_activation_context.cache.store_pending_focus_activation.assert_not_awaited()
