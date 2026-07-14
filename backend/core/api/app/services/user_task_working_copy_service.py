# backend/core/api/app/services/user_task_working_copy_service.py
#
# Tasks V1 transient working-copy storage. Main-processor task tools can stage
# private task edits for inference, but this service stores them only as
# short-lived vault-encrypted cache records. Durable task content persistence is
# still performed by authenticated clients using task-key encrypted fields.

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.core.api.app.services.directus.user_task_methods import hash_id


DEFAULT_TASK_WORKING_COPY_TTL_SECONDS = 15 * 60


class UserTaskWorkingCopyService:
    def __init__(self, *, cache_service: Any, payload_cipher: Any, ttl_seconds: int = DEFAULT_TASK_WORKING_COPY_TTL_SECONDS):
        self.cache_service = cache_service
        self.payload_cipher = payload_cipher
        self.ttl_seconds = ttl_seconds

    async def stage_private_update(
        self,
        *,
        owner_id: str,
        task_id: str,
        private_patch: dict[str, Any],
        safe_metadata: dict[str, Any],
        vault_key_id: str | None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if getattr(self.payload_cipher, "requires_vault_key_id", False) and not vault_key_id:
            raise RuntimeError("Vault key id is required to seal task working copies")

        current_time = int(now if now is not None else time.time())
        ref = f"vault://user-tasks/working-copies/{uuid.uuid4()}"
        payload = {
            "task_id": task_id,
            "private_patch": dict(private_patch),
            "safe_metadata": dict(safe_metadata),
        }
        encrypted = self.payload_cipher.encrypt_json(payload, vault_key_id)
        cache_value = {
            "ref": ref,
            "owner_hash": hash_id(owner_id),
            "task_id": task_id,
            "ciphertext": encrypted["ciphertext"],
            "checksum": encrypted.get("checksum"),
            "vault_key_ref": encrypted.get("vault_key_ref"),
            "key_version": encrypted.get("key_version"),
            "safe_metadata": dict(safe_metadata),
            "created_at": current_time,
            "expires_at": current_time + self.ttl_seconds,
        }
        cache_key = self._cache_key(ref)
        stored = await self.cache_service.set(cache_key, cache_value, ttl=self.ttl_seconds)
        if stored is False:
            raise RuntimeError("Failed to store task working copy")
        return {
            "ref": ref,
            "task_id": task_id,
            "safe_metadata": dict(safe_metadata),
            "expires_at": current_time + self.ttl_seconds,
        }

    async def load_private_update(
        self,
        *,
        owner_id: str,
        ref: str,
        vault_key_id: str | None,
    ) -> dict[str, Any]:
        if getattr(self.payload_cipher, "requires_vault_key_id", False) and not vault_key_id:
            raise RuntimeError("Vault key id is required to open task working copies")

        cached = await self.cache_service.get(self._cache_key(ref))
        if not isinstance(cached, dict) or cached.get("owner_hash") != hash_id(owner_id):
            raise ValueError("Task working copy not found")

        payload = self.payload_cipher.decrypt_json(
            {
                "ciphertext": cached.get("ciphertext"),
                "checksum": cached.get("checksum"),
                "vault_key_ref": cached.get("vault_key_ref"),
                "key_version": cached.get("key_version"),
            },
            vault_key_id,
        )
        if not isinstance(payload, dict):
            raise ValueError("Task working copy payload is invalid")
        return payload

    async def extend_private_update_ttl(self, *, owner_id: str, ref: str, ttl_seconds: int) -> None:
        cached = await self.cache_service.get(self._cache_key(ref))
        if not isinstance(cached, dict) or cached.get("owner_hash") != hash_id(owner_id):
            raise ValueError("Task working copy not found")
        cached["expires_at"] = int(time.time()) + ttl_seconds
        stored = await self.cache_service.set(self._cache_key(ref), cached, ttl=ttl_seconds)
        if stored is False:
            raise RuntimeError("Failed to extend task working copy")

    @staticmethod
    def _cache_key(ref: str) -> str:
        return f"user_task_working_copy:{hash_id(ref)}"
