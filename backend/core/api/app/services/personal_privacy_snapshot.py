"""Internal durable Personal privacy snapshots and socket-local send receipts."""
from __future__ import annotations

import os
import hashlib
import json
import time
import uuid
from typing import Any

from backend.core.api.app.schemas.auth import PersonalMemoriesSnapshot


async def read_personal_privacy_snapshot(directus: Any, user_id: str, known_generation: str | None = None) -> dict | None:
    """None means an older CMS/enforcement; callers must do a full fresh read."""
    secret = os.environ.get("INTERNAL_API_SHARED_TOKEN")
    if not secret:
        return None
    response = await directus._make_api_request(
        "POST", f"{directus.base_url}/personal-privacy-snapshot",
        json={"user_id": user_id, "known_generation": known_generation},
        headers={"x-internal-service-token": secret, "Cache-Control": "no-store"},
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError("Personal privacy snapshot unavailable")
    result = response.json().get("data")
    if not isinstance(result, dict):
        raise RuntimeError("Personal privacy snapshot invalid")
    if result.get("supported") is False:
        return None
    generation = result.get("privacy_generation")
    if (result.get("supported") is not True or not isinstance(generation, str)
            or not generation or len(generation) > 100 or type(result.get("unchanged")) is not bool):
        raise RuntimeError("Personal privacy generation invalid")
    if result["unchanged"]:
        if known_generation != generation or "personal_memories" in result:
            raise RuntimeError("Personal privacy equality invalid")
    else:
        result["personal_memories"] = PersonalMemoriesSnapshot.model_validate(result.get("personal_memories")).model_dump(mode="json")
    return result


class PersonalPrivacyReceiptCapacityError(RuntimeError):
    """All bounded slots are live; a valid pending proof is never evicted."""


class PersonalPrivacySocketState:
    """Bounded independent turn receipts, confined to the opening socket."""

    MAX_PENDING = 8
    # Existing snapshot admission permits at most 30 requests/session/minute.
    # Bound accepted replay records too, without dropping a live pending turn.
    MAX_TRACKED = 38
    RECEIPT_TTL_SECONDS = 30

    def __init__(self) -> None:
        self.prepared = False
        self.pending: dict[str, dict] = {}
        self.consumed: dict[str, dict] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for registry in (self.pending, self.consumed):
            for receipt_id, receipt in tuple(registry.items()):
                if receipt["expires_at"] <= now:
                    del registry[receipt_id]

    def can_issue(self) -> bool:
        self._prune()
        return (len(self.pending) < self.MAX_PENDING
                and len(self.pending) + len(self.consumed) < self.MAX_TRACKED)

    def issue(self, *, request: dict, auth: dict, generation: str | None) -> str:
        if not self.can_issue():
            raise PersonalPrivacyReceiptCapacityError("Personal privacy receipt capacity reached")
        receipt_id = str(uuid.uuid4())
        self.pending[receipt_id] = {
            "receipt_id": receipt_id, "turn_id": request["turn_id"],
            "generation": generation, "user_id": auth.get("user_id"),
            "session_hash": auth.get("session_hash"), "device_hash": auth.get("upgrade_device_hash"),
            "expires_at": time.monotonic() + self.RECEIPT_TTL_SECONDS,
        }
        return receipt_id

    @staticmethod
    def _fingerprint(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()).hexdigest()

    def mark_admitted(self, payload: dict) -> None:
        self._prune()
        receipt_id = payload.get("privacy_receipt_id")
        prior = self.consumed.get(receipt_id) if isinstance(receipt_id, str) else None
        if prior and prior["fingerprint"] == self._fingerprint(payload):
            prior["admitted"] = True

    def consume(self, payload: dict, auth: dict) -> bool:
        self._prune()
        receipt_id = payload.get("privacy_receipt_id")
        if not isinstance(receipt_id, str):
            return False
        # A failed targeted attempt consumes only that turn's proof; unrelated
        # slow encryption/preparation and accepted ACK replay remain usable.
        receipt = self.pending.pop(receipt_id, None)
        try:
            fingerprint = self._fingerprint(payload)
        except (TypeError, ValueError):
            return False
        if receipt is None:
            prior = self.consumed.get(receipt_id)
            receipt = prior if (prior and prior.get("admitted") is True
                                 and prior["fingerprint"] == fingerprint) else None
        valid = bool(receipt and time.monotonic() < receipt["expires_at"]
                     and payload.get("team_id") is None
                     and payload.get("privacy_generation") == receipt["generation"]
                     and payload.get("turn_id") == receipt["turn_id"]
                     and auth.get("user_id") == receipt["user_id"]
                     and auth.get("session_hash") == receipt["session_hash"]
                     and auth.get("upgrade_device_hash") == receipt["device_hash"])
        if valid and receipt is not self.consumed.get(receipt_id):
            self.consumed[receipt_id] = {**receipt, "fingerprint": fingerprint, "admitted": False}
        return valid


def privacy_v2_request(payload: object) -> dict | None:
    if (not isinstance(payload, dict) or not {"request_id", "purpose", "turn_id"} <= set(payload)
            or set(payload) - {"request_id", "purpose", "turn_id", "known_generation"}
            or payload.get("purpose") not in {"prepare", "send"}):
        return None
    for value in [payload.get("request_id"), *([payload.get("turn_id")] if payload["purpose"] == "send" else [])]:
        try:
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                return None
        except ValueError:
            return None
    if payload["purpose"] == "prepare" and payload["turn_id"] is not None:
        return None
    known = payload.get("known_generation")
    if known is not None and (not isinstance(known, str) or not known or len(known) > 100):
        return None
    return payload
