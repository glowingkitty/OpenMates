"""Encrypted, content-free artifact reference continuity for compressed chats."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Mapping, Optional


logger = logging.getLogger(__name__)

ARTIFACT_LEDGER_VERSION = 1
MAX_ARTIFACT_REFERENCES = 256
MAX_ARTIFACT_REF_CHARS = 512
_SAFE_EMBED_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _ledger_key(user_id_hash: str, chat_id: str) -> str:
    owner = hashlib.sha256(user_id_hash.encode("utf-8")).hexdigest()
    chat = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
    return f"ai:artifact-ledger:v{ARTIFACT_LEDGER_VERSION}:{owner}:{chat}"


def sanitize_artifact_index(index: Optional[Mapping[str, Any]]) -> dict[str, str]:
    """Keep only bounded reference-to-identifier metadata; never artifact content."""
    sanitized: dict[str, str] = {}
    for raw_ref, raw_embed_id in (index or {}).items():
        if not isinstance(raw_ref, str) or not isinstance(raw_embed_id, str):
            continue
        artifact_ref = raw_ref.strip()
        embed_id = raw_embed_id.strip()
        if (
            not artifact_ref
            or len(artifact_ref) > MAX_ARTIFACT_REF_CHARS
            or any(ord(character) < 32 for character in artifact_ref)
            or not _SAFE_EMBED_ID.fullmatch(embed_id)
        ):
            continue
        sanitized[artifact_ref] = embed_id
    return dict(list(sanitized.items())[-MAX_ARTIFACT_REFERENCES:])


async def load_and_merge_artifact_ledger(
    *,
    cache_service: Any,
    encryption_service: Any,
    user_vault_key_id: Optional[str],
    user_id_hash: str,
    chat_id: str,
    current_index: Optional[Mapping[str, Any]],
    persist: bool = True,
) -> dict[str, str]:
    """Merge encrypted historical refs with the current turn and refresh retention.

    Failures are deliberately non-fatal: callers retain the current request's
    artifact index and inference continues normally.
    """
    current = sanitize_artifact_index(current_index)
    if not persist:
        return current
    if not cache_service or not encryption_service or not user_vault_key_id:
        return current

    key = _ledger_key(user_id_hash, chat_id)
    try:
        client = await cache_service.client
        if not client:
            return current

        historical: dict[str, str] = {}
        encrypted_payload = await client.get(key)
        if isinstance(encrypted_payload, bytes):
            encrypted_payload = encrypted_payload.decode("utf-8")
        if isinstance(encrypted_payload, str) and encrypted_payload:
            plaintext = await encryption_service.decrypt_with_user_key(
                encrypted_payload,
                user_vault_key_id,
            )
            decoded = json.loads(plaintext) if plaintext else {}
            if isinstance(decoded, dict) and decoded.get("v") == ARTIFACT_LEDGER_VERSION:
                historical = sanitize_artifact_index(decoded.get("refs"))

        # Reinsert current refs so duplicate names point to the latest resolved embed.
        merged = dict(historical)
        for artifact_ref, embed_id in current.items():
            merged.pop(artifact_ref, None)
            merged[artifact_ref] = embed_id
        merged = dict(list(merged.items())[-MAX_ARTIFACT_REFERENCES:])

        if persist and merged:
            plaintext = json.dumps(
                {"v": ARTIFACT_LEDGER_VERSION, "refs": merged},
                separators=(",", ":"),
            )
            encrypted, _ = await encryption_service.encrypt_with_user_key(
                plaintext,
                user_vault_key_id,
            )
            ttl = int(getattr(cache_service, "CHAT_MESSAGES_TTL", 259200))
            await client.set(key, encrypted, ex=ttl)
        return merged
    except Exception as exc:
        logger.warning("Artifact reference ledger unavailable; using current refs (%s)", type(exc).__name__)
        return current


async def delete_artifact_ledger(cache_service: Any, user_id_hash: str, chat_id: str) -> bool:
    if not cache_service:
        return False
    return await cache_service.delete(_ledger_key(user_id_hash, chat_id))
