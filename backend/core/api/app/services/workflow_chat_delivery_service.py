"""Ciphertext-only pending delivery protocol for Workflow chat output.

This service owns the owner-device claim state machine for pending Workflow chat
output. Pending content is encrypted by the caller-provided Vault boundary;
regular chat keys are never created, accepted, or stored here.

Spec: docs/specs/workflows-cli-runtime/spec.yml
"""

from __future__ import annotations

import secrets
import hashlib
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

import httpx

from backend.shared.python_utils.content_hasher import hash_owner_id


class WorkflowChatDeliveryVaultCipher(Protocol):
    """Encrypts pending Workflow content at the Automation Vault boundary."""

    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        """Return Vault ciphertext for a pending delivery payload."""


class WorkflowChatDeliveryError(RuntimeError):
    """Base error for the isolated delivery state machine."""


class WorkflowChatDeliveryStateError(WorkflowChatDeliveryError):
    """A delivery cannot transition from its current terminal or claimed state."""


class WorkflowChatDeliveryStaleClaimError(WorkflowChatDeliveryError):
    """A claim token no longer owns the current fencing generation."""


@dataclass(frozen=True)
class WorkflowChatDeliveryClaim:
    """Opaque claim credentials returned only to the elected owner device."""

    token: str
    generation: int
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class WorkflowChatClientPersistence:
    """Client-supplied normal chat ciphertext written under the winning claim."""

    encrypted_chat_metadata: str
    encrypted_message: str
    persisted_at: int


@dataclass
class WorkflowChatDelivery:
    """Delivery metadata plus ciphertext, excluding the Vault plaintext payload."""

    delivery_id: str
    chat_id: str
    message_id: str
    owner_id: str = field(repr=False)
    encrypted_payload: str = field(repr=False)
    created_at: int
    expires_at: int
    owner_hash: str | None = field(default=None, repr=False)
    status: str = "delivery_pending"
    claim: WorkflowChatDeliveryClaim | None = None
    claim_generation: int = 0
    claim_token_hash: str | None = field(default=None, repr=False)
    claim_issued_at: int | None = None
    claim_expires_at: int | None = None
    claim_device_id: str | None = None
    client_persistence: WorkflowChatClientPersistence | None = None
    acknowledged_at: int | None = None
    cancelled_at: int | None = None
    expired_at: int | None = None


class WorkflowChatDeliveryRepository(Protocol):
    """Persistence boundary for pending Workflow chat deliveries."""

    def save_delivery(self, delivery: WorkflowChatDelivery) -> WorkflowChatDelivery:
        """Insert or replace a delivery row and return its stored snapshot."""

    def get_delivery(self, delivery_id: str, owner_id: str) -> WorkflowChatDelivery | None:
        """Return one owner-authorized delivery, if present."""

    def list_open_deliveries(self) -> list[WorkflowChatDelivery]:
        """Return non-terminal deliveries eligible for expiry scans."""

    def list_pending_for_owner(self, owner_id: str, *, limit: int = 50) -> list[WorkflowChatDelivery]:
        """Return owner deliveries that clients may claim or resume."""


class InMemoryWorkflowChatDeliveryRepository:
    """Thread-safe repository used by tests and local service injection."""

    def __init__(self) -> None:
        self._deliveries: dict[str, WorkflowChatDelivery] = {}
        self._lock = threading.RLock()

    def save_delivery(self, delivery: WorkflowChatDelivery) -> WorkflowChatDelivery:
        with self._lock:
            self._deliveries[delivery.delivery_id] = deepcopy(delivery)
            return deepcopy(delivery)

    def get_delivery(self, delivery_id: str, owner_id: str) -> WorkflowChatDelivery | None:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
            if delivery is None or delivery.owner_id != owner_id:
                return None
            return deepcopy(delivery)

    def list_open_deliveries(self) -> list[WorkflowChatDelivery]:
        with self._lock:
            return [deepcopy(delivery) for delivery in self._deliveries.values() if delivery.status not in WorkflowChatDeliveryService.TERMINAL_STATUSES]

    def list_pending_for_owner(self, owner_id: str, *, limit: int = 50) -> list[WorkflowChatDelivery]:
        with self._lock:
            deliveries = [
                deepcopy(delivery)
                for delivery in self._deliveries.values()
                if delivery.owner_id == owner_id and delivery.status == "delivery_pending"
            ]
        return sorted(deliveries, key=lambda delivery: delivery.created_at)[:limit]


class DirectusWorkflowChatDeliveryRepository:
    """Durable Workflow chat delivery repository backed by Directus."""

    COLLECTION = "workflow_chat_deliveries"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("CMS_URL") or "http://cms:8055").rstrip("/")
        self.token = token or os.getenv("DIRECTUS_TOKEN")
        self.admin_email = os.getenv("DATABASE_ADMIN_EMAIL")
        self.admin_password = os.getenv("DATABASE_ADMIN_PASSWORD")
        self._admin_token: str | None = None
        self._client = httpx.Client(timeout=5.0)

    @classmethod
    def from_directus_service(cls, directus_service: Any) -> "DirectusWorkflowChatDeliveryRepository":
        return cls(base_url=getattr(directus_service, "base_url", None), token=getattr(directus_service, "token", None))

    def save_delivery(self, delivery: WorkflowChatDelivery) -> WorkflowChatDelivery:
        payload = self._record_from_delivery(delivery)
        existing = self._find_one({"delivery_id": {"_eq": delivery.delivery_id}}, fields="id")
        if existing:
            self._patch_item(existing["id"], payload)
        else:
            self._create_item(payload)
        return self.get_delivery(delivery.delivery_id, delivery.owner_id) or replace(delivery)

    def get_delivery(self, delivery_id: str, owner_id: str) -> WorkflowChatDelivery | None:
        owner_hash = _owner_hash(owner_id)
        item = self._find_one(
            {"delivery_id": {"_eq": delivery_id}, "hashed_user_id": {"_eq": owner_hash}},
            fields="*",
        )
        return self._delivery_from_record(item, owner_id=owner_id) if item else None

    def list_open_deliveries(self) -> list[WorkflowChatDelivery]:
        return [
            self._delivery_from_record(item, owner_id="")
            for item in self._get_items({"status": {"_nin": list(WorkflowChatDeliveryService.TERMINAL_STATUSES)}}, fields="*")
        ]

    def list_pending_for_owner(self, owner_id: str, *, limit: int = 50) -> list[WorkflowChatDelivery]:
        owner_hash = _owner_hash(owner_id)
        items = self._get_items(
            {"hashed_user_id": {"_eq": owner_hash}, "status": {"_eq": "delivery_pending"}},
            fields="*",
            sort="created_at",
            limit=limit,
        )
        return [self._delivery_from_record(item, owner_id=owner_id) for item in items]

    def _record_from_delivery(self, delivery: WorkflowChatDelivery) -> dict[str, Any]:
        client_persistence = delivery.client_persistence
        return {
            "delivery_id": delivery.delivery_id,
            "hashed_user_id": delivery.owner_hash or _owner_hash(delivery.owner_id),
            "chat_id": delivery.chat_id,
            "message_id": delivery.message_id,
            "encrypted_payload": delivery.encrypted_payload,
            "status": delivery.status,
            "claim_generation": delivery.claim_generation,
            "claim_token_hash": delivery.claim_token_hash,
            "claim_issued_at": delivery.claim_issued_at,
            "claim_expires_at": delivery.claim_expires_at,
            "claim_device_id": delivery.claim_device_id,
            "encrypted_chat_metadata": client_persistence.encrypted_chat_metadata if client_persistence else None,
            "encrypted_message": client_persistence.encrypted_message if client_persistence else None,
            "client_persisted_at": client_persistence.persisted_at if client_persistence else None,
            "acknowledged_at": delivery.acknowledged_at,
            "cancelled_at": delivery.cancelled_at,
            "expired_at": delivery.expired_at,
            "created_at": delivery.created_at,
            "expires_at": delivery.expires_at,
        }

    @staticmethod
    def _delivery_from_record(item: dict[str, Any], *, owner_id: str) -> WorkflowChatDelivery:
        client_persistence = None
        if item.get("encrypted_chat_metadata") and item.get("encrypted_message"):
            client_persistence = WorkflowChatClientPersistence(
                encrypted_chat_metadata=str(item["encrypted_chat_metadata"]),
                encrypted_message=str(item["encrypted_message"]),
                persisted_at=int(item.get("client_persisted_at") or 0),
            )
        return WorkflowChatDelivery(
            delivery_id=str(item["delivery_id"]),
            chat_id=str(item["chat_id"]),
            message_id=str(item["message_id"]),
            owner_id=owner_id,
            encrypted_payload=str(item["encrypted_payload"]),
            created_at=int(item["created_at"]),
            expires_at=int(item["expires_at"]),
            owner_hash=str(item.get("hashed_user_id") or ""),
            status=str(item.get("status") or "delivery_pending"),
            claim_generation=int(item.get("claim_generation") or 0),
            claim_token_hash=item.get("claim_token_hash"),
            claim_issued_at=item.get("claim_issued_at"),
            claim_expires_at=item.get("claim_expires_at"),
            claim_device_id=item.get("claim_device_id"),
            client_persistence=client_persistence,
            acknowledged_at=item.get("acknowledged_at"),
            cancelled_at=item.get("cancelled_at"),
            expired_at=item.get("expired_at"),
        )

    def _find_one(self, filters: dict[str, Any], fields: str = "*") -> dict[str, Any] | None:
        items = self._get_items(filters, fields=fields, limit=1)
        return items[0] if items else None

    def _get_items(self, filters: dict[str, Any], *, fields: str = "*", sort: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"filter": json.dumps(filters), "fields": fields, "limit": limit, "_ts": str(time.time_ns())}
        if sort:
            params["sort"] = sort
        response = self._request("GET", f"/items/{self.COLLECTION}", params=params)
        data = response.json().get("data")
        if not isinstance(data, list):
            raise RuntimeError("Directus returned invalid Workflow chat delivery list response")
        return data

    def _create_item(self, payload: dict[str, Any]) -> None:
        self._request("POST", f"/items/{self.COLLECTION}", json=payload)

    def _patch_item(self, item_id: str, payload: dict[str, Any]) -> None:
        self._request("PATCH", f"/items/{self.COLLECTION}/{item_id}", json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Authorization", f"Bearer {self._token()}")
        response = self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if 200 <= response.status_code < 300:
            return response
        if response.status_code == 401:
            self._admin_token = None
            headers["Authorization"] = f"Bearer {self._admin_login_token()}"
            response = self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
            if 200 <= response.status_code < 300:
                return response
        response.raise_for_status()
        return response

    def _token(self) -> str:
        if self.token:
            return self.token
        return self._admin_login_token()

    def _admin_login_token(self) -> str:
        if self._admin_token:
            return self._admin_token
        if not self.admin_email or not self.admin_password:
            raise RuntimeError("Directus Workflow chat delivery repository requires DIRECTUS_TOKEN or admin credentials")
        response = self._client.post(
            f"{self.base_url}/auth/login",
            json={"email": self.admin_email, "password": self.admin_password},
        )
        if not (200 <= response.status_code < 300):
            raise RuntimeError(f"Directus admin login failed for Workflow chat delivery repository: {response.status_code}")
        token = response.json().get("data", {}).get("access_token")
        if not token:
            raise RuntimeError("Directus admin login did not return an access token")
        self._admin_token = str(token)
        return self._admin_token


class WorkflowChatDeliveryService:
    """Lock-protected pending chat delivery protocol."""

    TERMINAL_STATUSES = frozenset({"acknowledged", "cancelled", "expired"})

    def __init__(
        self,
        *,
        cipher: WorkflowChatDeliveryVaultCipher,
        repository: WorkflowChatDeliveryRepository | None = None,
        clock: Callable[[], int] | None = None,
        claim_ttl_seconds: int = 60,
    ) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        self._cipher = cipher
        self._repository = repository or InMemoryWorkflowChatDeliveryRepository()
        self._clock = clock or (lambda: int(time.time()))
        self._claim_ttl_seconds = claim_ttl_seconds
        self._lock = threading.RLock()

    def create_delivery(
        self,
        *,
        owner_id: str,
        title: str,
        message: str,
        expires_at: int,
        chat_id: str | None = None,
    ) -> WorkflowChatDelivery:
        """Accept one pending delivery and retain its content only as Vault ciphertext."""
        if not owner_id:
            raise ValueError("owner_id is required")
        if not title:
            raise ValueError("title is required")
        if not message:
            raise ValueError("message is required")
        now = self._now()
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")

        delivery_id = str(uuid.uuid4())
        encrypted_payload = self._cipher.encrypt_delivery(
            owner_id=owner_id,
            delivery_id=delivery_id,
            payload={"title": title, "message": message},
        )
        if not encrypted_payload:
            raise ValueError("Vault cipher returned empty ciphertext")
        delivery = WorkflowChatDelivery(
            delivery_id=delivery_id,
            chat_id=chat_id or str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_hash=_owner_hash(owner_id),
            encrypted_payload=encrypted_payload,
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock:
            delivery = self._repository.save_delivery(delivery)
        return self._snapshot(delivery)

    def create_encrypted_delivery(
        self,
        *,
        owner_id: str,
        encrypted_payload: str,
        expires_at: int,
        chat_id: str | None = None,
    ) -> WorkflowChatDelivery:
        """Accept one already Vault-encrypted pending delivery payload."""
        if not owner_id:
            raise ValueError("owner_id is required")
        if not encrypted_payload:
            raise ValueError("encrypted_payload is required")
        now = self._now()
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
        delivery = WorkflowChatDelivery(
            delivery_id=str(uuid.uuid4()),
            chat_id=chat_id or str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_hash=_owner_hash(owner_id),
            encrypted_payload=encrypted_payload,
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock:
            delivery = self._repository.save_delivery(delivery)
        return self._snapshot(delivery)

    def list_pending_for_owner(self, *, owner_id: str, limit: int = 50) -> list[WorkflowChatDelivery]:
        """Return owner-authorized deliveries that can be offered to clients."""
        with self._lock:
            deliveries = self._repository.list_pending_for_owner(owner_id, limit=limit)
            result: list[WorkflowChatDelivery] = []
            for delivery in deliveries:
                if self._expire_if_due(delivery):
                    self._repository.save_delivery(delivery)
                    continue
                result.append(self._snapshot(delivery))
            return result

    def get_delivery(self, *, delivery_id: str, owner_id: str) -> WorkflowChatDelivery:
        """Return one owner-authorized delivery without exposing Vault plaintext."""
        with self._lock:
            delivery = self._require_owner_delivery(delivery_id, owner_id)
            self._expire_if_due(delivery)
            return self._snapshot(delivery)

    def claim_new_chat_delivery(
        self,
        *,
        delivery_id: str,
        owner_id: str,
        device_id: str,
    ) -> WorkflowChatDeliveryClaim:
        """Atomically elect one owner device to encrypt a new regular chat."""
        if not device_id:
            raise ValueError("device_id is required")
        with self._lock:
            delivery = self._require_owner_delivery(delivery_id, owner_id)
            self._expire_if_due(delivery)
            self._require_claimable(delivery)
            now = self._now()
            if delivery.claim is not None and delivery.claim.expires_at > now:
                if delivery.claim_device_id == device_id:
                    return delivery.claim
                raise WorkflowChatDeliveryStateError("Delivery is already claimed")
            if delivery.claim_expires_at is not None and delivery.claim_expires_at > now:
                raise WorkflowChatDeliveryStateError("Delivery is already claimed")
            if delivery.claim is not None or delivery.claim_token_hash is not None:
                delivery.status = "delivery_pending"
                delivery.claim = None
                delivery.claim_token_hash = None
                delivery.claim_issued_at = None
                delivery.claim_expires_at = None
                delivery.claim_device_id = None

            generation = delivery.claim_generation + 1
            claim = WorkflowChatDeliveryClaim(
                token=secrets.token_urlsafe(32),
                generation=generation,
                issued_at=now,
                expires_at=now + self._claim_ttl_seconds,
            )
            delivery.status = "claimed"
            delivery.claim = claim
            delivery.claim_generation = generation
            delivery.claim_token_hash = _hash_claim_token(claim.token)
            delivery.claim_issued_at = claim.issued_at
            delivery.claim_expires_at = claim.expires_at
            delivery.claim_device_id = device_id
            self._repository.save_delivery(delivery)
            return claim

    def persist_client_ciphertext(
        self,
        *,
        delivery_id: str,
        owner_id: str,
        claim: WorkflowChatDeliveryClaim,
        encrypted_chat_metadata: str,
        encrypted_message: str,
        device_id: str | None = None,
    ) -> WorkflowChatDelivery:
        """Accept winning client ciphertext only under the current claim fence."""
        if not encrypted_chat_metadata or not encrypted_message:
            raise ValueError("encrypted chat metadata and message are required")
        with self._lock:
            delivery = self._require_owner_delivery(delivery_id, owner_id)
            self._require_current_claim(delivery, claim)
            self._require_claim_device(delivery, device_id)
            persistence = WorkflowChatClientPersistence(
                encrypted_chat_metadata=encrypted_chat_metadata,
                encrypted_message=encrypted_message,
                persisted_at=self._now(),
            )
            if delivery.client_persistence is not None:
                if delivery.client_persistence.encrypted_chat_metadata != encrypted_chat_metadata or delivery.client_persistence.encrypted_message != encrypted_message:
                    raise WorkflowChatDeliveryStateError("Client ciphertext conflicts with the persisted delivery")
                return self._snapshot(delivery)
            delivery.client_persistence = persistence
            self._repository.save_delivery(delivery)
            return self._snapshot(delivery)

    def acknowledge_delivery(
        self,
        *,
        delivery_id: str,
        owner_id: str,
        claim: WorkflowChatDeliveryClaim,
        device_id: str | None = None,
    ) -> WorkflowChatDelivery:
        """Complete a persisted delivery; repeat acknowledgement is idempotent."""
        with self._lock:
            delivery = self._require_owner_delivery(delivery_id, owner_id)
            if delivery.status == "acknowledged" and self._claim_matches(delivery, claim):
                return self._snapshot(delivery)
            self._require_current_claim(delivery, claim)
            self._require_claim_device(delivery, device_id)
            if delivery.client_persistence is None:
                raise WorkflowChatDeliveryStateError("Client ciphertext must be persisted before acknowledgement")
            delivery.status = "acknowledged"
            delivery.acknowledged_at = self._now()
            self._repository.save_delivery(delivery)
            return self._snapshot(delivery)

    def cancel_delivery(self, *, delivery_id: str, owner_id: str) -> WorkflowChatDelivery:
        """Terminally cancel an unacknowledged owner delivery."""
        with self._lock:
            delivery = self._require_owner_delivery(delivery_id, owner_id)
            if delivery.status == "cancelled":
                return self._snapshot(delivery)
            if delivery.status == "acknowledged":
                raise WorkflowChatDeliveryStateError("Acknowledged delivery cannot be cancelled")
            if delivery.status == "expired":
                return self._snapshot(delivery)
            delivery.status = "cancelled"
            delivery.cancelled_at = self._now()
            self._repository.save_delivery(delivery)
            return self._snapshot(delivery)

    def expire_delivery(self, *, delivery_id: str, owner_id: str) -> WorkflowChatDelivery:
        """Terminally expire one unacknowledged owner delivery."""
        with self._lock:
            delivery = self._require_owner_delivery(delivery_id, owner_id)
            if delivery.status in {"acknowledged", "cancelled", "expired"}:
                return self._snapshot(delivery)
            delivery.status = "expired"
            delivery.expired_at = self._now()
            self._repository.save_delivery(delivery)
            return self._snapshot(delivery)

    def expire_due_deliveries(self) -> list[str]:
        """Mark due unacknowledged deliveries expired and return their stable IDs."""
        with self._lock:
            expired: list[str] = []
            for delivery in self._repository.list_open_deliveries():
                if self._expire_if_due(delivery):
                    self._repository.save_delivery(delivery)
                    expired.append(delivery.delivery_id)
            return expired

    def _require_owner_delivery(self, delivery_id: str, owner_id: str) -> WorkflowChatDelivery:
        delivery = self._repository.get_delivery(delivery_id, owner_id)
        if delivery is None:
            raise PermissionError("Workflow chat delivery not found")
        return delivery

    def _require_claimable(self, delivery: WorkflowChatDelivery) -> None:
        if delivery.status in self.TERMINAL_STATUSES:
            raise WorkflowChatDeliveryStateError(f"Delivery is {delivery.status}")
        if delivery.client_persistence is not None:
            raise WorkflowChatDeliveryStateError("Delivery ciphertext is already persisted")

    def _require_current_claim(self, delivery: WorkflowChatDelivery, claim: WorkflowChatDeliveryClaim) -> None:
        self._expire_if_due(delivery)
        if delivery.status in self.TERMINAL_STATUSES:
            raise WorkflowChatDeliveryStateError(f"Delivery is {delivery.status}")
        if not self._claim_matches(delivery, claim) or claim.expires_at <= self._now():
            if delivery.claim_expires_at is not None and delivery.claim_expires_at <= self._now():
                self._clear_claim(delivery)
                self._repository.save_delivery(delivery)
            raise WorkflowChatDeliveryStaleClaimError("Delivery claim is stale")

    @staticmethod
    def _require_claim_device(delivery: WorkflowChatDelivery, device_id: str | None) -> None:
        if device_id is not None and delivery.claim_device_id != device_id:
            raise WorkflowChatDeliveryStaleClaimError("Delivery claim belongs to another device")

    def _expire_if_due(self, delivery: WorkflowChatDelivery) -> bool:
        if delivery.status in self.TERMINAL_STATUSES or delivery.expires_at > self._now():
            return False
        delivery.status = "expired"
        delivery.expired_at = self._now()
        return True

    @staticmethod
    def _claim_matches(delivery: WorkflowChatDelivery, claim: WorkflowChatDeliveryClaim) -> bool:
        return (
            delivery.claim_generation == claim.generation
            and delivery.claim_token_hash == _hash_claim_token(claim.token)
            and delivery.claim_expires_at == claim.expires_at
        )

    @staticmethod
    def _clear_claim(delivery: WorkflowChatDelivery) -> None:
        delivery.status = "delivery_pending"
        delivery.claim = None
        delivery.claim_token_hash = None
        delivery.claim_issued_at = None
        delivery.claim_expires_at = None
        delivery.claim_device_id = None

    @staticmethod
    def _snapshot(delivery: WorkflowChatDelivery) -> WorkflowChatDelivery:
        return replace(delivery)

    def _now(self) -> int:
        return int(self._clock())


def _hash_claim_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _owner_hash(owner_id: str) -> str:
    owner_hash = hash_owner_id(owner_id)
    if not owner_hash:
        raise ValueError("owner_id is required")
    return owner_hash
