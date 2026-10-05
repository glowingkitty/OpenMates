"""Exact-turn Focus continuation and owner-scoped terminal failure regressions."""

import json
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.shared.python_utils.focus_continuation_history import (
    FocusContinuationHistoryError,
    publish_current_focus_continuation_failure,
    rebuild_focus_continuation_history,
)


def _row(role: str, row_id: str | None, content: str, **fields: str) -> str:
    return json.dumps({
        "role": role, "encrypted_content": content, "created_at": 1,
        **({"id": row_id} if row_id else {}), **fields,
    })


def _cache(rows: list[str], latest: str = "source") -> SimpleNamespace:
    return SimpleNamespace(
        get=AsyncMock(return_value=latest),
        get_ai_messages_history=AsyncMock(return_value=rows),
        publish_event=AsyncMock(),
        get_user_vault_key_id=AsyncMock(return_value="vault-key"),
        get_and_delete_pending_focus_activation=AsyncMock(),
        client=AsyncMock(),
    )


def _crypto() -> SimpleNamespace:
    return SimpleNamespace(decrypt_with_user_key=AsyncMock(side_effect=lambda content, key: content))


def _pending(**fields: str) -> dict:
    return {
        "user_id": "owner", "user_id_hash": "owner-hash", "chat_id": "chat",
        "message_id": "source", "focus_id": "jobs-career_insights",
        "embed_id": "activation", **fields,
    }


# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
@pytest.mark.asyncio
async def test_rebuilder_anchors_exact_source_and_preserves_older_transitions() -> None:
    rows = [
        _row("assistant", "provisional", "Partial assistant text"),
        _row("assistant", "activation", '{"type":"focus_mode_activation"}'),
        _row("user", None, "Current request", client_message_id="source"),
        _row("system", "prior-transition", "Prior focus transition"),
        _row("assistant", "prior-answer", "Prior answer"),
        _row("user", "prior-user", "Prior request"),
    ]
    history = await rebuild_focus_continuation_history(
        cache_service=_cache(rows), encryption_service=_crypto(),
        pending_context=_pending(), user_vault_key_id="vault-key",
    )
    assert [item["role"] for item in history] == ["user", "assistant", "system", "user"]
    assert [item["content"] for item in history] == [
        "Prior request", "Prior answer", "Prior focus transition", "Current request",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rows", "latest", "code"),
    [
        ([_row("assistant", "other", "Old answer")], "source", "missing_source_turn"),
        ([_row("user", "source", "A"), _row("user", None, "B", message_id="source")],
         "source", "ambiguous_source_turn"),
        ([_row("assistant", "source", "Wrong role")], "source", "invalid_source_turn"),
        ([_row("user", "source", "Current")], "newer", "stale_source_turn"),
        ([_row("user", "newer", "Later"), _row("user", "source", "Current")],
         "source", "stale_source_turn"),
    ],
)
# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
async def test_rebuilder_fails_closed_for_missing_duplicate_invalid_or_newer_source(
    rows: list[str], latest: str, code: str,
) -> None:
    with pytest.raises(FocusContinuationHistoryError) as error:
        await rebuild_focus_continuation_history(
            cache_service=_cache(rows, latest), encryption_service=_crypto(),
            pending_context=_pending(), user_vault_key_id="vault-key",
        )
    assert error.value.code == code


# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
@pytest.mark.asyncio
async def test_rebuilder_rechecks_source_after_decryption() -> None:
    cache = _cache([_row("user", "source", "Current")])

    async def decrypt(content: str, key: str) -> str:
        cache.get.return_value = "newer"
        return content

    crypto = SimpleNamespace(decrypt_with_user_key=AsyncMock(side_effect=decrypt))
    with pytest.raises(FocusContinuationHistoryError) as error:
        await rebuild_focus_continuation_history(
            cache_service=cache, encryption_service=crypto,
            pending_context=_pending(), user_vault_key_id="vault-key",
        )
    assert error.value.code == "stale_source_turn"


# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
@pytest.mark.asyncio
async def test_logical_queued_head_takes_precedence_over_physical_message_id() -> None:
    cache = _cache([_row("user", None, "Queued head", clientMessageId="logical")], "logical")
    history = await rebuild_focus_continuation_history(
        cache_service=cache, encryption_service=_crypto(),
        pending_context=_pending(agentic_context_turn_id="logical"), user_vault_key_id="vault-key",
    )
    assert history[-1]["content"] == "Queued head"


# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
@pytest.mark.asyncio
async def test_failure_event_uses_only_fixed_scoped_fields_for_current_turn() -> None:
    cache = _cache([], "source")
    assert await publish_current_focus_continuation_failure(cache, _pending()) is True
    assert cache.publish_event.await_args.args == (
        "user_cache_events:owner",
        {"event_type": "focus_mode_continuation_failed",
         "payload": {"chat_id": "chat", "user_message_id": "source"}},
    )
    cache.get.return_value = "newer"
    assert await publish_current_focus_continuation_failure(cache, _pending()) is False
    assert cache.publish_event.await_count == 1
    cache.get.return_value = "source"
    cache.get_ai_messages_history.return_value = [
        _row("user", "newer", "Later"), _row("user", "source", "Current"),
    ]
    assert await publish_current_focus_continuation_failure(cache, _pending()) is False
    assert cache.publish_event.await_count == 1


# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_real_focus_dispatch_branches_use_exact_source_history(
    monkeypatch: pytest.MonkeyPatch, accepted: bool,
) -> None:
    rows = [
        _row("assistant", "provisional", "Do not replay this"),
        _row("assistant", "activation", '{"type": "focus_mode_activation"}'),
        _row("user", "source", "Current request"),
        _row("system", "prior-transition", "Prior transition"),
    ]
    cache = _cache(rows)
    cache.get_and_delete_pending_focus_activation.return_value = _pending()
    redis = SimpleNamespace(publish=AsyncMock())
    cache.client = AsyncMock(return_value=redis)()
    from backend.core.api.app.services import cache as cache_module
    from backend.core.api.app.services import directus as directus_module
    from backend.core.api.app.utils import encryption as encryption_module
    from backend.core.api.app.services import project_write_authorization_service as auth_module
    from backend.apps.ai.processing import focus_phases
    from backend.apps.ai.tasks import ask_skill_task
    from backend.shared.python_utils import recent_work_summary_client
    monkeypatch.setattr(cache_module, "CacheService", lambda: cache)
    monkeypatch.setattr(directus_module, "DirectusService", lambda: SimpleNamespace(ensure_auth_token=AsyncMock()))
    monkeypatch.setattr(encryption_module, "EncryptionService", _crypto)
    accept = AsyncMock()
    monkeypatch.setattr(auth_module.ProjectWriteAuthorizationService, "accept_specialist_focus", accept)
    monkeypatch.setattr(focus_phases, "invalidate_phase_runtime", AsyncMock())
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", AsyncMock(side_effect=lambda value: value))
    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", AsyncMock(side_effect=lambda value, request_id: value))
    sent = []
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async",
                        Mock(side_effect=lambda **kwargs: sent.append(kwargs) or SimpleNamespace(id="continued")))
    if accepted:
        confirm = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
        monkeypatch.setattr(confirm, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": ["test"]})
        await confirm._async_focus_mode_auto_confirm("chat", "task-id")
        assert accept.await_count == 1
        assert sent[0]["kwargs"]["request_data_dict"]["active_focus_id"] == "jobs-career_insights"
    else:
        from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as reject
        monkeypatch.setattr(reject, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": ["test"]})
        await reject._trigger_continuation_without_focus(
            cache, SimpleNamespace(), _crypto(), _pending(), "test",
        )
        assert sent[0]["kwargs"]["request_data_dict"]["active_focus_id"] is None
    request = sent[0]["kwargs"]["request_data_dict"]
    assert request["message_id"] == "source"
    assert [row["content"] for row in request["message_history"]] == ["Prior transition", "Current request"]
    cache.publish_event.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize(
    ("rows", "latest", "should_publish"),
    [
        ([_row("assistant", "old", "Prior answer")], "source", True),
        ([_row("user", "source", "A"), _row("user", "source", "B")], "source", True),
        ([_row("user", "source", "Current request")], "newer", False),
        ([_row("user", "newer", "Later"), _row("user", "source", "Current request")],
         "source", False),
    ],
)
# contract-test: supporting surface=rest_api assertions=focus-modes.history-events,focus-modes.off-instruction
async def test_dispatch_branches_never_start_inference_from_missing_duplicate_or_stale_source(
    monkeypatch: pytest.MonkeyPatch, accepted: bool, rows: list[str],
    latest: str, should_publish: bool,
) -> None:
    cache = _cache(rows, latest)
    cache.get_and_delete_pending_focus_activation.return_value = _pending()
    from backend.core.api.app.services import cache as cache_module
    from backend.core.api.app.services import directus as directus_module
    from backend.core.api.app.utils import encryption as encryption_module
    from backend.core.api.app.services import project_write_authorization_service as auth_module
    from backend.apps.ai.tasks import ask_skill_task
    from backend.shared.python_utils import recent_work_summary_client
    monkeypatch.setattr(cache_module, "CacheService", lambda: cache)
    monkeypatch.setattr(directus_module, "DirectusService", lambda: SimpleNamespace(ensure_auth_token=AsyncMock()))
    monkeypatch.setattr(encryption_module, "EncryptionService", _crypto)
    accept = AsyncMock()
    monkeypatch.setattr(auth_module.ProjectWriteAuthorizationService, "accept_specialist_focus", accept)
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", AsyncMock(side_effect=lambda value: value))
    dispatch = Mock(return_value=SimpleNamespace(id="continued"))
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    if accepted:
        confirm = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
        await confirm._async_focus_mode_auto_confirm("chat", "task-id")
        accept.assert_not_awaited()
    else:
        from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as reject
        await reject._trigger_continuation_without_focus(
            cache, SimpleNamespace(), _crypto(), _pending(), "test",
        )
    dispatch.assert_not_called()
    assert cache.publish_event.await_count == int(should_publish)


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("advance_key", [True, False])
# contract-test: supporting surface=rest_api assertions=focus-modes.history-events,focus-modes.off-instruction
async def test_dispatch_branches_recheck_source_after_context_sealing(
    monkeypatch: pytest.MonkeyPatch, accepted: bool, advance_key: bool,
) -> None:
    cache = _cache([_row("user", "source", "Current request")])
    cache.get_and_delete_pending_focus_activation.return_value = _pending()
    redis = SimpleNamespace(publish=AsyncMock())
    cache.client = AsyncMock(return_value=redis)()
    from backend.core.api.app.services import cache as cache_module
    from backend.core.api.app.services import directus as directus_module
    from backend.core.api.app.utils import encryption as encryption_module
    from backend.core.api.app.services import project_write_authorization_service as auth_module
    from backend.apps.ai.processing import focus_phases
    from backend.apps.ai.tasks import ask_skill_task
    from backend.shared.python_utils import recent_work_summary_client
    monkeypatch.setattr(cache_module, "CacheService", lambda: cache)
    monkeypatch.setattr(directus_module, "DirectusService", lambda: SimpleNamespace(ensure_auth_token=AsyncMock()))
    monkeypatch.setattr(encryption_module, "EncryptionService", _crypto)
    monkeypatch.setattr(auth_module.ProjectWriteAuthorizationService, "accept_specialist_focus", AsyncMock())
    monkeypatch.setattr(focus_phases, "invalidate_phase_runtime", AsyncMock())
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", AsyncMock(side_effect=lambda value: value))

    async def seal(value: dict, request_id: str) -> dict:
        if advance_key:
            cache.get.return_value = "newer"
        else:
            cache.get_ai_messages_history.return_value = [
                _row("user", "newer", "Later"), _row("user", "source", "Current request"),
            ]
        return value

    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", AsyncMock(side_effect=seal))
    dispatch = Mock(return_value=SimpleNamespace(id="continued"))
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    if accepted:
        confirm = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
        monkeypatch.setattr(confirm, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": ["test"]})
        await confirm._async_focus_mode_auto_confirm("chat", "task-id")
    else:
        from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as reject
        monkeypatch.setattr(reject, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": ["test"]})
        await reject._trigger_continuation_without_focus(cache, SimpleNamespace(), _crypto(), _pending(), "test")
    dispatch.assert_not_called()
    cache.publish_event.assert_not_awaited()
    assert recent_work_summary_client.seal_private_context_payload.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
# contract-test: supporting surface=rest_api assertions=focus-modes.history-events,focus-modes.off-instruction
async def test_newer_cached_user_during_decryption_blocks_stale_focus_activation(
    monkeypatch: pytest.MonkeyPatch, accepted: bool,
) -> None:
    cache = _cache([_row("user", "source", "Current request")])
    cache.get_and_delete_pending_focus_activation.return_value = _pending()
    redis = SimpleNamespace(publish=AsyncMock())
    cache.client = AsyncMock(return_value=redis)()

    async def decrypt(content: str, key: str) -> str:
        cache.get_ai_messages_history.return_value = [
            _row("user", "newer", "Later"), _row("user", "source", "Current request"),
        ]
        return content

    crypto = SimpleNamespace(decrypt_with_user_key=AsyncMock(side_effect=decrypt))
    from backend.core.api.app.services import cache as cache_module
    from backend.core.api.app.services import directus as directus_module
    from backend.core.api.app.utils import encryption as encryption_module
    from backend.core.api.app.services import project_write_authorization_service as auth_module
    from backend.apps.ai.tasks import ask_skill_task
    from backend.shared.python_utils import recent_work_summary_client
    monkeypatch.setattr(cache_module, "CacheService", lambda: cache)
    monkeypatch.setattr(directus_module, "DirectusService", lambda: SimpleNamespace(ensure_auth_token=AsyncMock()))
    monkeypatch.setattr(encryption_module, "EncryptionService", lambda: crypto)
    accept = AsyncMock()
    monkeypatch.setattr(auth_module.ProjectWriteAuthorizationService, "accept_specialist_focus", accept)
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", AsyncMock(side_effect=lambda value: value))
    dispatch = Mock(return_value=SimpleNamespace(id="continued"))
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", dispatch)
    if accepted:
        confirm = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
        await confirm._async_focus_mode_auto_confirm("chat", "task-id")
        accept.assert_not_awaited()
        redis.publish.assert_not_awaited()
    else:
        from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as reject
        await reject._trigger_continuation_without_focus(cache, SimpleNamespace(), crypto, _pending(), "test")
    dispatch.assert_not_called()
    cache.publish_event.assert_not_awaited()
    assert cache.get.return_value == "source"


# contract-test: supporting surface=rest_api assertions=focus-modes.history-events
@pytest.mark.asyncio
async def test_cache_listener_forwards_only_current_owner_scoped_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import websockets
    sent = []
    manager = SimpleNamespace(
        get_connections_for_user=lambda user: {"device": object()},
        send_personal_message=AsyncMock(side_effect=lambda **kwargs: sent.append(kwargs)),
    )
    monkeypatch.setattr(websockets, "manager", manager)
    latest = "source"

    async def messages(_pattern: str):
        for source in ("source", "older"):
            yield {"channel": "user_cache_events:owner", "data": {
                "event_type": "focus_mode_continuation_failed",
                "payload": {"chat_id": "chat", "user_message_id": source, "private": "not forwarded"},
            }}

    cache = SimpleNamespace(
        client=AsyncMock()(),
        get=AsyncMock(side_effect=lambda key: latest),
        subscribe_to_channel=messages,
    )
    await websockets.listen_for_cache_events(SimpleNamespace(state=SimpleNamespace(cache_service=cache)))
    assert len(sent) == 1
    assert sent[0]["user_id"] == "owner"
    assert sent[0]["message"]["type"] == "error"
    assert sent[0]["message"]["payload"] == {
        "code": "focus_mode_continuation_failed",
        "message": "Focus continuation could not complete. Please try again.",
        "chat_id": "chat", "user_message_id": "source",
    }
