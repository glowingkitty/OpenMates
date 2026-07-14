"""Focused contracts for isolated pending Workflow chat delivery.

The protocol stores only Vault ciphertext until a client wins a fenced claim and
supplies normal encrypted chat/message payloads. These tests intentionally do
not involve Workflow routes, runners, or regular chat persistence.

Spec: docs/specs/workflows-cli-runtime/spec.yml
"""

from __future__ import annotations

import pytest

from backend.core.api.app.services.workflow_chat_delivery_service import (
    DirectusWorkflowChatDeliveryRepository,
    WorkflowChatDeliveryStateError,
    WorkflowChatDeliveryStaleClaimError,
    WorkflowChatDeliveryService,
)


class FakeVaultCipher:
    """Deterministic fake that makes plaintext leaks visible in assertions."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, str]] = []

    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        del owner_id
        self.payloads.append(payload)
        return f"vault:{delivery_id}"


def test_pending_delivery_encrypts_private_content_without_a_regular_chat_key() -> None:
    cipher = FakeVaultCipher()
    service = WorkflowChatDeliveryService(cipher=cipher, clock=lambda: 100)

    delivery = service.create_delivery(
        owner_id="alice",
        title="Weather update",
        message="Rain is expected this afternoon.",
        expires_at=200,
    )

    assert delivery.status == "delivery_pending"
    assert delivery.encrypted_payload.startswith("vault:")
    assert cipher.payloads == [{"title": "Weather update", "message": "Rain is expected this afternoon."}]
    assert "Weather update" not in repr(delivery)
    assert "Rain is expected" not in repr(delivery)
    assert not hasattr(delivery, "chat_key")
    assert not hasattr(service, "chat_key")


def test_claim_is_fenced_and_expired_claim_can_be_reclaimed() -> None:
    now = [100]
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: now[0], claim_ttl_seconds=10)
    delivery = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)

    first_claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="phone")
    assert service.claim_new_chat_delivery(
        delivery_id=delivery.delivery_id, owner_id="alice", device_id="phone"
    ) == first_claim

    with pytest.raises(WorkflowChatDeliveryStateError, match="claimed"):
        service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="laptop")

    now[0] = 111
    second_claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="laptop")
    assert second_claim.generation == first_claim.generation + 1
    assert second_claim.token != first_claim.token


def test_stale_claim_cannot_persist_or_acknowledge_after_reclaim() -> None:
    now = [100]
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: now[0], claim_ttl_seconds=10)
    delivery = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    stale_claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="phone")
    now[0] = 111
    winning_claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="laptop")

    with pytest.raises(WorkflowChatDeliveryStaleClaimError):
        service.persist_client_ciphertext(
            delivery_id=delivery.delivery_id,
            owner_id="alice",
            claim=stale_claim,
            encrypted_chat_metadata="chat-ciphertext-from-phone",
            encrypted_message="message-ciphertext-from-phone",
        )
    with pytest.raises(WorkflowChatDeliveryStaleClaimError):
        service.acknowledge_delivery(delivery_id=delivery.delivery_id, owner_id="alice", claim=stale_claim)

    pending = service.get_delivery(delivery_id=delivery.delivery_id, owner_id="alice")
    assert pending.client_persistence is None
    persisted = service.persist_client_ciphertext(
        delivery_id=delivery.delivery_id,
        owner_id="alice",
        claim=winning_claim,
        encrypted_chat_metadata="chat-ciphertext-from-laptop",
        encrypted_message="message-ciphertext-from-laptop",
    )
    assert persisted.status == "claimed"
    assert persisted.client_persistence is not None

    acknowledged = service.acknowledge_delivery(delivery_id=delivery.delivery_id, owner_id="alice", claim=winning_claim)
    assert acknowledged.status == "acknowledged"
    assert service.acknowledge_delivery(delivery_id=delivery.delivery_id, owner_id="alice", claim=winning_claim).status == "acknowledged"


def test_reconnect_advertises_only_unclaimed_pending_deliveries() -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: 100)
    pending = service.create_delivery(owner_id="alice", title="Pending", message="Message", expires_at=200)
    claimed = service.create_delivery(owner_id="alice", title="Claimed", message="Message", expires_at=200)
    persisted = service.create_delivery(owner_id="alice", title="Persisted", message="Message", expires_at=200)

    claimed_claim = service.claim_new_chat_delivery(
        delivery_id=claimed.delivery_id,
        owner_id="alice",
        device_id="phone",
    )
    persisted_claim = service.claim_new_chat_delivery(
        delivery_id=persisted.delivery_id,
        owner_id="alice",
        device_id="phone",
    )
    service.persist_client_ciphertext(
        delivery_id=persisted.delivery_id,
        owner_id="alice",
        claim=persisted_claim,
        encrypted_chat_metadata="metadata",
        encrypted_message="message",
        device_id="phone",
    )

    offered_ids = {
        delivery.delivery_id
        for delivery in service.list_pending_for_owner(owner_id="alice")
    }

    assert offered_ids == {pending.delivery_id}
    assert claimed_claim.token


def test_claim_token_is_bound_to_the_claiming_device_when_supplied() -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: 100)
    delivery = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="phone")

    with pytest.raises(WorkflowChatDeliveryStaleClaimError, match="another device"):
        service.persist_client_ciphertext(
            delivery_id=delivery.delivery_id,
            owner_id="alice",
            claim=claim,
            encrypted_chat_metadata="metadata",
            encrypted_message="message",
            device_id="laptop",
        )

    service.persist_client_ciphertext(
        delivery_id=delivery.delivery_id,
        owner_id="alice",
        claim=claim,
        encrypted_chat_metadata="metadata",
        encrypted_message="message",
        device_id="phone",
    )
    with pytest.raises(WorkflowChatDeliveryStaleClaimError, match="another device"):
        service.acknowledge_delivery(delivery_id=delivery.delivery_id, owner_id="alice", claim=claim, device_id="laptop")


def test_directus_record_stores_claim_token_hash_without_raw_claim_token() -> None:
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: 100)
    delivery = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    claim = service.claim_new_chat_delivery(delivery_id=delivery.delivery_id, owner_id="alice", device_id="phone")
    claimed = service.get_delivery(delivery_id=delivery.delivery_id, owner_id="alice")

    record = DirectusWorkflowChatDeliveryRepository(base_url="http://directus.example", token="token")._record_from_delivery(claimed)

    assert record["claim_token_hash"]
    assert claim.token not in str(record)
    assert "claim" not in record
    restored = DirectusWorkflowChatDeliveryRepository._delivery_from_record(record, owner_id="alice")
    assert restored.claim is None
    assert restored.claim_token_hash == record["claim_token_hash"]


def test_owner_checks_and_terminal_cancellation_or_expiry_block_delivery() -> None:
    now = [100]
    service = WorkflowChatDeliveryService(cipher=FakeVaultCipher(), clock=lambda: now[0])
    cancelled = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)

    with pytest.raises(PermissionError):
        service.claim_new_chat_delivery(delivery_id=cancelled.delivery_id, owner_id="bob", device_id="phone")

    assert service.cancel_delivery(delivery_id=cancelled.delivery_id, owner_id="alice").status == "cancelled"
    assert service.cancel_delivery(delivery_id=cancelled.delivery_id, owner_id="alice").status == "cancelled"
    with pytest.raises(WorkflowChatDeliveryStateError, match="cancelled"):
        service.claim_new_chat_delivery(delivery_id=cancelled.delivery_id, owner_id="alice", device_id="phone")

    expiring = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=105)
    now[0] = 105
    assert service.expire_due_deliveries() == [expiring.delivery_id]
    assert service.get_delivery(delivery_id=expiring.delivery_id, owner_id="alice").status == "expired"
    with pytest.raises(WorkflowChatDeliveryStateError, match="expired"):
        service.claim_new_chat_delivery(delivery_id=expiring.delivery_id, owner_id="alice", device_id="phone")

    manual_expiry = service.create_delivery(owner_id="alice", title="Title", message="Message", expires_at=200)
    assert service.expire_delivery(delivery_id=manual_expiry.delivery_id, owner_id="alice").status == "expired"
