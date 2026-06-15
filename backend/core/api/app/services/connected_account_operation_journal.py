# backend/core/api/app/services/connected_account_operation_journal.py
#
# Privacy-preserving operation journal helpers for connected-account actions.
# Journal entries store hashes and Vault-encrypted receipt/scope payloads only;
# provider tokens and plaintext account identities are rejected.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

FORBIDDEN_JOURNAL_FIELDS = {
    "refresh_token",
    "access_token",
    "provider_email",
    "account_email",
    "provider_account_id",
}


@dataclass(frozen=True)
class ConnectedAccountJournalEntry:
    """Validated connected-account operation journal entry."""

    id: str
    action_id: str
    hashed_user_id: str
    connected_account_id_hash: str
    app_id_hash: str
    action: str
    decision: str
    encrypted_action_scope: str | None
    encrypted_receipt: str | None
    encrypted_undo_payload: str | None
    created_at: int
    expires_at: int | None = None


class ConnectedAccountOperationJournalService:
    """Create encrypted journal rows for connected-account receipts and undo."""

    def __init__(self, *, encryption_service: Any) -> None:
        self.encryption = encryption_service

    async def build_entry(
        self,
        *,
        user_id: str,
        user_vault_key_id: str,
        connected_account_id: str,
        app_id: str,
        action: str,
        decision: str,
        action_id: str | None = None,
        action_scope: dict[str, Any] | None = None,
        receipt: dict[str, Any] | None = None,
        undo_payload: dict[str, Any] | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        payloads = {
            "action_scope": action_scope or {},
            "receipt": receipt or {},
            "undo_payload": undo_payload or {},
        }
        _reject_forbidden_fields(payloads)
        encrypted_action_scope = await self._encrypt_optional(action_scope, user_vault_key_id)
        encrypted_receipt = await self._encrypt_optional(receipt, user_vault_key_id)
        encrypted_undo_payload = await self._encrypt_optional(undo_payload, user_vault_key_id)
        entry_id = str(uuid.uuid4())
        entry = {
            "id": entry_id,
            "action_id": action_id or entry_id,
            "hashed_user_id": _sha256(user_id),
            "connected_account_id_hash": _sha256(connected_account_id),
            "chat_id_hash": _sha256(chat_id) if chat_id else None,
            "message_id_hash": _sha256(message_id) if message_id else None,
            "app_id_hash": _sha256(app_id),
            "action": action,
            "decision": decision,
            "encrypted_action_scope": encrypted_action_scope,
            "encrypted_receipt": encrypted_receipt,
            "encrypted_undo_payload": encrypted_undo_payload,
            "created_at": int(time.time()),
            "expires_at": expires_at,
        }
        return {key: value for key, value in entry.items() if value is not None}

    async def record_entry(self, *, directus_service: Any, **entry_kwargs: Any) -> dict[str, Any]:
        """Build and persist a journal entry in Directus."""

        entry = await self.build_entry(**entry_kwargs)
        result = await directus_service.create_item("connected_account_operation_journal", entry)
        if isinstance(result, tuple):
            success, payload = result[0], result[1] if len(result) > 1 else None
            if not success:
                raise RuntimeError("failed to persist connected-account operation journal entry")
            return payload or entry
        return result or entry

    async def load_owned_action(
        self,
        *,
        directus_service: Any,
        user_id: str,
        action_id: str,
    ) -> dict[str, Any] | None:
        """Load a journal entry by opaque action id and user hash."""

        rows = await directus_service.get_items(
            "connected_account_operation_journal",
            params={
                "filter[action_id][_eq]": action_id,
                "filter[hashed_user_id][_eq]": _sha256(user_id),
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    async def decrypt_undo_payload(self, *, entry: dict[str, Any], user_vault_key_id: str) -> dict[str, Any]:
        encrypted = entry.get("encrypted_undo_payload")
        if not encrypted:
            return {}
        plaintext = await self.encryption.decrypt_with_user_key(str(encrypted), user_vault_key_id)
        payload = json.loads(plaintext)
        return payload if isinstance(payload, dict) else {}

    async def mark_undone(
        self,
        *,
        directus_service: Any,
        entry: dict[str, Any],
        receipt: dict[str, Any],
        user_vault_key_id: str,
    ) -> dict[str, Any]:
        """Mark an operation as undone with an encrypted undo receipt."""

        _reject_forbidden_fields({"receipt": receipt})
        encrypted_receipt = await self._encrypt_optional(receipt, user_vault_key_id)
        payload = {
            "decision": "undo_success",
            "encrypted_receipt": encrypted_receipt,
            "undone_at": int(time.time()),
        }
        updated = await directus_service.update_item(
            "connected_account_operation_journal",
            str(entry["id"]),
            payload,
        )
        if not updated:
            raise RuntimeError("failed to mark connected-account operation as undone")
        return updated

    async def _encrypt_optional(self, value: dict[str, Any] | None, key_id: str) -> str | None:
        if not value:
            return None
        encrypted, _ = await self.encryption.encrypt_with_user_key(json.dumps(value), key_id)
        return encrypted


def _reject_forbidden_fields(value: Any) -> None:
    serialized = json.dumps(value)
    forbidden = sorted(field for field in FORBIDDEN_JOURNAL_FIELDS if f'"{field}"' in serialized)
    if forbidden:
        raise ValueError("operation journal payload contains forbidden fields: " + ", ".join(forbidden))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
