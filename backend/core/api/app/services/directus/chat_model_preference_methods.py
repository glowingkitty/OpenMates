# backend/core/api/app/services/directus/chat_model_preference_methods.py
#
# Directus methods for the encrypted per-user/per-chat AI model selector.
# The backend owns only row identity, owner scope, versioning, and opaque
# ciphertext storage. It must never persist the decrypted selected model; clients
# decrypt locally and pass a transient exact model only with authorized inference.

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService


logger = logging.getLogger(__name__)

COLLECTION_NAME = "user_chat_preferences"
PREFERENCE_FIELDS = "id,hashed_user_id,chat_id,encrypted_selected_ai_model,preference_v,updated_at"
MIN_FORMAT_D_BYTES = 28
MAX_ENCRYPTED_SELECTION_BYTES = 8192
VAULT_CIPHERTEXT_PREFIX = "vault:v1:"


class ChatModelPreferenceConflictError(RuntimeError):
    def __init__(self, server_record: dict[str, Any] | None):
        super().__init__("chat_model_preference_conflict")
        self.server_record = server_record


class ChatModelPreferenceValidationError(ValueError):
    pass


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


def validate_encrypted_selected_ai_model(value: Any) -> str:
    """Accept only client-side Format D ciphertext, never plaintext or Vault text."""

    if not isinstance(value, str) or not value.strip():
        raise ChatModelPreferenceValidationError("encrypted_selected_ai_model is required")
    encrypted_value = value.strip()
    if encrypted_value.startswith(VAULT_CIPHERTEXT_PREFIX):
        raise ChatModelPreferenceValidationError("Vault ciphertext is not allowed for chat model preferences")
    if len(encrypted_value.encode("utf-8")) > MAX_ENCRYPTED_SELECTION_BYTES:
        raise ChatModelPreferenceValidationError("encrypted_selected_ai_model exceeds the maximum size")
    try:
        decoded = base64.b64decode(encrypted_value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ChatModelPreferenceValidationError("encrypted_selected_ai_model must be client-encrypted base64") from exc
    if len(decoded) < MIN_FORMAT_D_BYTES or decoded[:2] == b"OM":
        raise ChatModelPreferenceValidationError("encrypted_selected_ai_model must use master-key Format D ciphertext")
    return encrypted_value


def normalize_preference_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {
        "id": record.get("id"),
        "hashed_user_id": record.get("hashed_user_id"),
        "chat_id": record.get("chat_id"),
        "encrypted_selected_ai_model": record.get("encrypted_selected_ai_model"),
        "preference_v": int(record.get("preference_v") or 0),
        "updated_at": int(record.get("updated_at") or 0),
    }


def _record_matches_patch(record: dict[str, Any] | None, patch: dict[str, Any]) -> bool:
    return bool(record) and all(record.get(field) == value for field, value in patch.items())


class ChatModelPreferenceMethods:
    def __init__(self, service: DirectusService):
        self._service = service

    async def get_preference(self, user_id: str, chat_id: str) -> dict[str, Any] | None:
        hashed_user_id = hash_user_id(user_id)
        rows = await self._service.get_items(
            COLLECTION_NAME,
            params={
                "filter": {
                    "hashed_user_id": {"_eq": hashed_user_id},
                    "chat_id": {"_eq": chat_id},
                },
                "fields": PREFERENCE_FIELDS,
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        return normalize_preference_record(rows[0]) if rows else None

    async def upsert_preference(
        self,
        *,
        user_id: str,
        chat_id: str,
        encrypted_selected_ai_model: str,
        expected_preference_v: int | None = None,
    ) -> dict[str, Any]:
        encrypted_value = validate_encrypted_selected_ai_model(encrypted_selected_ai_model)
        current = await self.get_preference(user_id, chat_id)
        now = int(time.time())
        hashed_user_id = hash_user_id(user_id)

        if current:
            current_version = int(current.get("preference_v") or 0)
            if expected_preference_v is not None and expected_preference_v != current_version:
                raise ChatModelPreferenceConflictError(current)
            patch = {
                "encrypted_selected_ai_model": encrypted_value,
                "preference_v": current_version + 1,
                "updated_at": now,
            }
            if expected_preference_v is not None:
                updated = await self._service.update_item_if_version(
                    COLLECTION_NAME,
                    str(current["id"]),
                    patch,
                    expected_preference_v,
                    version_field="preference_v",
                    extra_filters={"chat_id": chat_id},
                    owner_hash_field="hashed_user_id",
                    owner_hash=hashed_user_id,
                    admin_required=True,
                )
                if not updated:
                    refreshed = await self.get_preference(user_id, chat_id)
                    if _record_matches_patch(refreshed, patch):
                        updated = refreshed
                    else:
                        raise ChatModelPreferenceConflictError(refreshed)
            else:
                updated = await self._service.update_item(
                    COLLECTION_NAME,
                    str(current["id"]),
                    patch,
                    admin_required=True,
                )
            normalized = normalize_preference_record({**current, **(updated or {})})
            if normalized:
                return normalized
            raise RuntimeError("chat_model_preference_update_failed")

        if expected_preference_v not in (None, 0):
            raise ChatModelPreferenceConflictError(None)

        success, created = await self._service.create_item(
            COLLECTION_NAME,
            {
                "hashed_user_id": hashed_user_id,
                "chat_id": chat_id,
                "encrypted_selected_ai_model": encrypted_value,
                "preference_v": 1,
                "updated_at": now,
            },
            admin_required=True,
        )
        if success and isinstance(created, dict):
            return normalize_preference_record(created) or created
        logger.error("Failed to create chat model preference for chat %s: %s", chat_id, created)
        raise RuntimeError("chat_model_preference_create_failed")
