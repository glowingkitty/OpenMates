"""Separate, purpose-bound sealed delivery for generated private-chat metadata.

Reuses the registered completion-recovery public key, never its plaintext
assistant contract. Only sealed bytes and encrypted-field names cross storage.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import uuid
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.shared.python_utils.chat_completion_recovery import (
    _canonical_uuid, _decode, _encode, _envelope_key, _key_version, _length_prefixed,
)

logger = logging.getLogger(__name__)

MAX_METADATA_BYTES = 64 * 1024
METADATA_FIELDS = {
    "title": "encrypted_title", "summary": "encrypted_chat_summary",
    "category": "encrypted_category", "icon": "encrypted_icon",
}
STAGES = {"initial", "postprocessing"}


def metadata_associated_data(*, owner_id: str, chat_id: str, task_id: str,
                             job_id: str, stage: str, key_version: int) -> bytes:
    if stage not in STAGES:
        raise ValueError("unsupported metadata stage")
    return (
        b"OMCM1"
        + b"".join(_length_prefixed(_canonical_uuid(value, field)) for field, value in (
            ("owner_id", owner_id), ("chat_id", chat_id), ("task_id", task_id), ("job_id", job_id),
        ))
        + _length_prefixed(stage) + struct.pack(">I", _key_version(key_version))
    )


def build_sealed_metadata_job_data(*, owner_id: str, owner_hash: str, chat_id: str,
                                   task_id: str, inference_task_id: str, preflight_id: str,
                                   recovery_public_key: str, chat_key_version: int,
                                   stage: str, metadata: dict[str, str | None], source_metadata_v: int = 0,
                                   ephemeral_private_key: str | None = None,
                                   nonce: str | None = None, generated_at: str | None = None) -> dict[str, Any]:
    if set(metadata) - METADATA_FIELDS.keys():
        raise ValueError("unsupported metadata field")
    fields = {field: value for field, value in metadata.items() if value is not None and value != ""}
    if not fields or any(not isinstance(value, str) for value in fields.values()):
        raise ValueError("metadata must contain nonempty strings")
    job_id = str(uuid.uuid5(uuid.UUID(task_id), f"chat-metadata:{stage}"))
    identity = dict(owner_id=owner_id, chat_id=chat_id, task_id=task_id,
                    job_id=job_id, stage=stage, key_version=chat_key_version)
    plaintext = json.dumps({**identity, "metadata": fields}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(plaintext) > MAX_METADATA_BYTES:
        raise ValueError("metadata exceeds 64 KiB")
    aad = metadata_associated_data(**identity)
    ephemeral_bytes = _decode(ephemeral_private_key, "ephemeral_private_key") if ephemeral_private_key else os.urandom(32)
    nonce_bytes = _decode(nonce, "nonce") if nonce else os.urandom(12)
    if len(nonce_bytes) != 12:
        raise ValueError("invalid nonce length")
    ephemeral = x25519.X25519PrivateKey.from_private_bytes(ephemeral_bytes)
    key = _envelope_key(ephemeral, _decode(recovery_public_key, "recovery_public_key"), aad)
    envelope = {
        "v": 1,
        "epk": _encode(ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
        "nonce": _encode(nonce_bytes),
        "ciphertext": _encode(AESGCM(key).encrypt(nonce_bytes, plaintext, aad)),
    }
    return {
        "protocol_version": 1, "job_id": job_id, "hashed_user_id": owner_hash,
        "chat_id": chat_id, "task_id": task_id, "inference_task_id": inference_task_id,
        "preflight_id": preflight_id, "chat_key_version": chat_key_version, "stage": stage,
        "source_metadata_v": source_metadata_v,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "encrypted_fields": sorted(METADATA_FIELDS[field] for field in fields),
        "sealed_payload": json.dumps(envelope, sort_keys=True, separators=(",", ":")),
    }


def open_metadata_envelope(envelope: dict[str, Any], *, recovery_private_key: str,
                           **identity: Any) -> dict[str, Any]:
    if set(envelope) != {"v", "epk", "nonce", "ciphertext"} or envelope["v"] != 1:
        raise ValueError("unsupported metadata envelope")
    ciphertext = _decode(envelope["ciphertext"], "ciphertext")
    nonce = _decode(envelope["nonce"], "nonce")
    if len(ciphertext) > MAX_METADATA_BYTES + 16 or len(nonce) != 12:
        raise ValueError("invalid metadata envelope size")
    private = x25519.X25519PrivateKey.from_private_bytes(_decode(recovery_private_key, "recovery_private_key"))
    aad = metadata_associated_data(**identity)
    key = _envelope_key(private, _decode(envelope["epk"], "epk"), aad)
    payload = json.loads(AESGCM(key).decrypt(nonce, ciphertext, aad))
    if set(payload) != {*identity, "metadata"} or any(payload.get(k) != v for k, v in identity.items()):
        raise ValueError("metadata identity mismatch")
    fields = payload["metadata"]
    if not isinstance(fields, dict) or not fields or set(fields) - METADATA_FIELDS.keys():
        raise ValueError("invalid metadata fields")
    if any(not isinstance(value, str) or not value for value in fields.values()):
        raise ValueError("invalid metadata values")
    return payload


async def persist_generated_metadata(*, request: Any, task_id: str, stage: str,
                                     metadata: dict[str, str | None]) -> dict[str, Any] | None:
    """Seal before transient publication; never retain server-decryptable content."""
    inference_id = request.resolved_recovery_inference_task_id()
    if (not inference_id or getattr(request, "is_external", False)
            or getattr(request, "is_incognito", False) or getattr(request, "team_id", None)):
        return None
    if not any(value for value in metadata.values()):
        return None
    data = None
    directus = None
    try:
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
        from backend.core.api.app.services.directus import DirectusService

        data = build_sealed_metadata_job_data(
            owner_id=request.user_id, owner_hash=request.user_id_hash, chat_id=request.chat_id,
            task_id=task_id, inference_task_id=inference_id, preflight_id=request.recovery_preflight_id,
            recovery_public_key=request.recovery_public_key, chat_key_version=request.chat_key_version,
            stage=stage, metadata=metadata, source_metadata_v=max(
                int(getattr(request, "current_chat_metadata_v", None) or 0),
                int(getattr(request, "current_chat_title_v", None) or 0),
            ),
        )
        directus = DirectusService()
        return await ChatRecoveryService(directus).execute("create_metadata_job", data)
    except Exception:
        # Enqueue only already-sealed bytes. Metadata outage cannot abort paid
        # inference or turn a completed answer into a reported inference failure.
        if data is not None:
            try:
                queue_metadata_retry(data)
            except Exception:
                logger.error("Sealed metadata retry enqueue unavailable; transient delivery remains active")
        else:
            logger.warning("Metadata sealing unavailable; transient delivery remains active")
        return None
    finally:
        if directus is not None:
            try:
                await directus.close()
            except Exception:
                logger.warning("Metadata persistence connection cleanup unavailable")


def queue_metadata_retry(data: dict[str, Any]) -> None:
    from backend.core.api.app.tasks.celery_config import app as celery_app

    celery_app.send_task("app.tasks.persistence_tasks.persist_chat_metadata_recovery",
                         args=[data], queue="persistence", countdown=1, expires=7 * 24 * 60 * 60,
                         task_id=f"chat-metadata-persistence:{data['job_id']}", retry=False)
