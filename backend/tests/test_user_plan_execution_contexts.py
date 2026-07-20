"""Tests for short-lived Plans V1 execution context and cleanup contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods, hash_id
from backend.core.api.app.services.user_plan_service import UserPlanService


@pytest.mark.asyncio
async def test_save_execution_context_stores_vault_ciphertext_for_primary_chat() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "plan-row", "plan_id": "plan-1", "primary_chat_id": "chat-1"}])
    directus.create_item = AsyncMock(return_value=(True, {"id": "ctx-1", "expires_at": 500}))

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.save_execution_context(
        "plan-1",
        "user-1",
        {"vault_encrypted_context": "vault-cipher", "context_version": 1, "created_at": 100, "expires_at": 500},
    )

    assert result == {"plan_id": "plan-1", "expires_at": 500}
    collection, record = directus.create_item.await_args.args
    assert collection == "user_plan_execution_contexts"
    assert record["vault_encrypted_context"] == "vault-cipher"
    assert record["hashed_user_id"] == hash_id("user-1")
    assert record["hashed_primary_chat_id"] == hash_id("chat-1")
    assert "plaintext" not in record


@pytest.mark.asyncio
async def test_active_context_returns_missing_blocker_when_context_absent() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.active_context("user-1", "chat-1", 200)

    assert result["active_plan"] is None
    assert result["blockers"] == [{"kind": "execution_context", "status": "missing_or_expired"}]


@pytest.mark.asyncio
async def test_cleanup_deletes_expired_contexts_and_orphan_key_wrappers() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "ctx-expired"}],
        [{"id": "wrapper-orphan", "hashed_plan_id": hash_id("missing-plan")}],
        [{"plan_id": "existing-plan"}],
    ])
    directus.delete_item = AsyncMock(return_value=True)

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.cleanup_expired_plan_data(200)

    assert result == {"expired_execution_contexts": 1, "orphan_key_wrappers": 1}
    assert directus.delete_item.await_args_list[0].args == ("user_plan_execution_contexts", "ctx-expired")
    assert directus.delete_item.await_args_list[1].args == ("user_plan_key_wrappers", "wrapper-orphan")
