"""Saved-chat cleanup cannot precede a verified permanent deletion fence."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services import chat_deletion_fence
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


ROOT = Path(__file__).resolve().parents[2]
CHAT_ID = "00000000-0000-4000-8000-000000000011"
USER_ID = "00000000-0000-4000-8000-000000000012"
OWNER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()


def _receipt() -> dict:
    return {"chat_deletion_fenced": True, "chat_id": CHAT_ID}


def _install_recovery(monkeypatch, *, receipt=None, error=None):
    execute = AsyncMock(return_value=_receipt() if receipt is None else receipt)
    if error is not None:
        execute.side_effect = error
    monkeypatch.setattr(
        chat_deletion_fence, "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=execute),
    )
    return execute


def _actual_function(relative: str, name: str, namespace: dict):
    """Exercise the real entry boundary without loading unrelated Celery services."""
    path = ROOT / relative
    tree = ast.parse(path.read_text())
    node = next(node for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    node.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        node,
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_authenticated_actor_gets_exact_fence_receipt(monkeypatch) -> None:
    execute = _install_recovery(monkeypatch)
    directus = SimpleNamespace(get_items=AsyncMock())
    receipt = asyncio.run(chat_deletion_fence.require_chat_deletion_fence(
        directus, CHAT_ID, hashed_user_id=OWNER_HASH,
    ))
    assert receipt == _receipt()
    directus.get_items.assert_not_awaited()
    execute.assert_awaited_once_with("invalidate_deletion", {
        "protocol_version": 1, "hashed_user_id": OWNER_HASH,
        "scope": "chat", "chat_id": CHAT_ID,
    })


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_internal_personal_cleanup_resolves_current_owner_without_payloads(monkeypatch) -> None:
    execute = _install_recovery(monkeypatch)
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[{
        "id": CHAT_ID, "hashed_user_id": OWNER_HASH, "hashed_team_id": None,
    }]))
    asyncio.run(chat_deletion_fence.require_chat_deletion_fence(directus, CHAT_ID))
    directus.get_items.assert_awaited_once_with("chats", params={
        "filter[id][_eq]": CHAT_ID, "fields": "id,hashed_user_id,hashed_team_id", "limit": 1,
    }, no_cache=True)
    assert execute.await_args.args[1]["hashed_user_id"] == OWNER_HASH


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_team_cleanup_requires_an_explicit_authenticated_actor(monkeypatch) -> None:
    execute = _install_recovery(monkeypatch)
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[{
        "id": CHAT_ID, "hashed_user_id": OWNER_HASH, "hashed_team_id": "b" * 64,
    }]))
    with pytest.raises(ChatRecoveryProtocolError) as rejected:
        asyncio.run(chat_deletion_fence.require_chat_deletion_fence(directus, CHAT_ID))
    assert rejected.value.code == "team_delete_actor_required"
    execute.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.parametrize("rows", [None, [], [{"id": "wrong", "hashed_user_id": OWNER_HASH}]])
def test_missing_or_failed_metadata_never_authorizes_cleanup(monkeypatch, rows) -> None:
    execute = _install_recovery(monkeypatch)
    with pytest.raises(ChatRecoveryProtocolError):
        asyncio.run(chat_deletion_fence.require_chat_deletion_fence(
            SimpleNamespace(get_items=AsyncMock(return_value=rows)), CHAT_ID,
        ))
    execute.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.parametrize("receipt", [
    {}, {"chat_deletion_fenced": False, "chat_id": CHAT_ID},
    {"chat_deletion_fenced": True, "chat_id": "wrong"},
    {"chat_deletion_fenced": 1, "chat_id": CHAT_ID}, [],
])
def test_chat_record_cleanup_rejects_old_or_malformed_receipts(monkeypatch, receipt) -> None:
    _install_recovery(monkeypatch, receipt=receipt)
    directus = SimpleNamespace(delete_item=AsyncMock(return_value=True))
    actor = SimpleNamespace(
        directus_service=directus,
        cleanup_assistant_speech_for_chat=AsyncMock(),
    )
    delete = _actual_function(
        "backend/core/api/app/services/directus/chat_methods.py", "persist_delete_chat",
        {"logger": logging.getLogger(__name__)},
    )
    assert asyncio.run(delete(actor, CHAT_ID, hashed_user_id=OWNER_HASH)) is False
    actor.cleanup_assistant_speech_for_chat.assert_not_awaited()
    directus.delete_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_chat_record_cleanup_occurs_after_confirmed_fence(monkeypatch) -> None:
    events = []

    async def fence(*_args):
        events.append("fence")
        return _receipt()

    async def speech(_chat_id):
        events.append("speech")

    async def delete_item(**_kwargs):
        events.append("delete")
        return True

    monkeypatch.setattr(chat_deletion_fence, "ChatRecoveryService", lambda _service: SimpleNamespace(execute=fence))
    actor = SimpleNamespace(
        directus_service=SimpleNamespace(delete_item=delete_item),
        cleanup_assistant_speech_for_chat=speech,
    )
    delete = _actual_function(
        "backend/core/api/app/services/directus/chat_methods.py", "persist_delete_chat",
        {"logger": logging.getLogger(__name__)},
    )
    assert asyncio.run(delete(actor, CHAT_ID, hashed_user_id=OWNER_HASH)) is True
    assert events == ["fence", "speech", "delete"]


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_async_cleanup_aborts_before_workflows_archive_or_content(monkeypatch) -> None:
    failure = ChatRecoveryProtocolError(503, "fence_unavailable")
    execute = _install_recovery(monkeypatch, error=failure)
    directus = SimpleNamespace(ensure_auth_token=AsyncMock(return_value=True))
    cleanup = _actual_function(
        "backend/core/api/app/tasks/persistence_tasks.py", "_async_persist_delete_chat",
        {"logger": logging.getLogger(__name__), "DirectusService": lambda: directus},
    )
    with pytest.raises(ChatRecoveryProtocolError) as rejected:
        asyncio.run(cleanup(USER_ID, CHAT_ID))
    assert rejected.value is failure
    assert execute.await_args.args[1]["hashed_user_id"] == OWNER_HASH
    directus.ensure_auth_token.assert_awaited_once()
