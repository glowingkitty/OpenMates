# backend/tests/test_connected_account_operation_journal.py
#
# Tests for privacy-preserving connected-account operation journal entries.
# Journal rows must contain only hashes and encrypted payloads, never provider
# tokens or plaintext account identity.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json

import pytest

from backend.tests.test_token_broker_refs import FakeEncryption


@pytest.mark.anyio
async def test_operation_journal_encrypts_receipts_and_hashes_identifiers() -> None:
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )

    service = ConnectedAccountOperationJournalService(encryption_service=FakeEncryption())
    entry = await service.build_entry(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="write",
        decision="completed",
        action_scope={"calendar_id": "primary"},
        receipt={"summary": "Created event"},
        undo_payload={"provider_revision": "etag-1"},
        chat_id="chat-1",
        message_id="msg-1",
    )

    serialized = json.dumps(entry)
    assert "user-1" not in serialized
    assert "acct-1" not in serialized
    assert "Created event" not in serialized
    assert entry["encrypted_receipt"].startswith("vault:vault-key:")


@pytest.mark.anyio
async def test_operation_journal_rejects_provider_tokens() -> None:
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )

    service = ConnectedAccountOperationJournalService(encryption_service=FakeEncryption())
    with pytest.raises(ValueError, match="refresh_token"):
        await service.build_entry(
            user_id="user-1",
            user_vault_key_id="vault-key",
            connected_account_id="acct-1",
            app_id="calendar",
            action="write",
            decision="failed",
            receipt={"refresh_token": "secret"},
        )


@pytest.mark.anyio
async def test_operation_journal_persists_entry_to_directus() -> None:
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )

    class FakeDirectus:
        def __init__(self) -> None:
            self.collection = ""
            self.payload: dict | None = None

        async def create_item(self, collection: str, payload: dict):
            self.collection = collection
            self.payload = payload
            return True, {"id": payload["id"]}

    directus = FakeDirectus()
    service = ConnectedAccountOperationJournalService(encryption_service=FakeEncryption())
    result = await service.record_entry(
        directus_service=directus,
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="write",
        decision="completed",
        receipt={"summary": "Created event"},
    )

    assert directus.collection == "connected_account_operation_journal"
    assert directus.payload is not None
    assert directus.payload["encrypted_receipt"].startswith("vault:vault-key:")
    assert result["id"] == directus.payload["id"]
    assert result["action_id"] == directus.payload["action_id"]
