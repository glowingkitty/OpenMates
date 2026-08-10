# backend/tests/test_task_working_copy_privacy.py
#
# Red-phase privacy tests for Tasks V1 working copies. AI task tools may handle
# plaintext during inference, but that content must be sealed into a short-lived
# vault-encrypted cache record before any client-encrypted durable Directus
# update exists.

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.user_task_working_copy_service import UserTaskWorkingCopyService


class FakePayloadCipher:
    requires_vault_key_id = True

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def encrypt_json(self, payload: dict, vault_key_id: str | None) -> dict:
        assert vault_key_id == "vault-key-1"
        self.payloads.append(payload)
        return {
            "ciphertext": "vault:ciphertext",
            "checksum": "checksum-1",
            "vault_key_ref": vault_key_id,
            "key_version": 1,
        }


@pytest.mark.asyncio
async def test_private_task_update_is_cached_only_as_vault_ciphertext() -> None:
    cache = AsyncMock()
    cipher = FakePayloadCipher()
    service = UserTaskWorkingCopyService(cache_service=cache, payload_cipher=cipher, ttl_seconds=900)

    result = await service.stage_private_update(
        owner_id="user-1",
        task_id="TASK-123",
        private_patch={"title": "Launch plan", "description": "Private acceptance criteria"},
        safe_metadata={"status": "todo", "expected_version": 2},
        vault_key_id="vault-key-1",
        now=100,
    )

    assert result["ref"].startswith("vault://user-tasks/working-copies/")
    assert result["expires_at"] == 1000
    cache.set.assert_awaited_once()
    cached_value = cache.set.await_args.args[1]
    assert cached_value["ciphertext"] == "vault:ciphertext"
    assert cached_value["safe_metadata"] == {"status": "todo", "expected_version": 2}
    assert "Launch plan" not in str(cached_value)
    assert "Private acceptance criteria" not in str(cached_value)
    assert cipher.payloads == [
        {
            "task_id": "TASK-123",
            "private_patch": {"title": "Launch plan", "description": "Private acceptance criteria"},
            "safe_metadata": {"status": "todo", "expected_version": 2},
        }
    ]


@pytest.mark.asyncio
async def test_working_copy_stage_rejects_missing_vault_key() -> None:
    cache = AsyncMock()
    service = UserTaskWorkingCopyService(cache_service=cache, payload_cipher=FakePayloadCipher(), ttl_seconds=900)

    with pytest.raises(RuntimeError, match="Vault key id"):
        await service.stage_private_update(
            owner_id="user-1",
            task_id="TASK-123",
            private_patch={"title": "Launch plan"},
            safe_metadata={"expected_version": 2},
            vault_key_id=None,
            now=100,
        )

    cache.set.assert_not_awaited()
