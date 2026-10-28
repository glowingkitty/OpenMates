"""WebSocket handler for client-encrypted embed diff rows.

Embed version history follows the same zero-knowledge storage rule as embeds:
the backend may receive plaintext during the active AI turn, but persisted
`embed_diffs` rows are encrypted by the client with the parent embed key before
they are sent back for Directus storage.
"""

import hashlib
import logging
from typing import Any, Dict

from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.embed_version_transaction_service import (
    EmbedVersionTransactionService, EmbedVersionTransactionError, requires_atomic_project_embed_write,
)

logger = logging.getLogger(__name__)


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


async def _send_store_embed_diff_confirmed(
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    request_id: Any,
    embed_id: str,
    version_number: int,
    canonical_digest: str,
) -> None:
    if not request_id:
        return
    await manager.send_personal_message(
        {
            "type": "store_embed_diff_confirmed",
            "payload": {
                "request_id": request_id,
                "embed_id": embed_id,
                "version_number": version_number,
                "canonical_digest": canonical_digest,
                "canonical_source": "version_row",
            },
        },
        user_id,
        device_fingerprint_hash,
    )


async def handle_store_embed_diff(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    """Store a client-encrypted embed version row in `embed_diffs`."""
    del websocket, cache_service

    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        _otel_span, _otel_token = start_ws_handler_span(
            "store_embed_diff",
            user_id,
            payload,
            user_otel_attrs,
        )
    except Exception:
        pass

    try:
        embed_id = str(payload.get("embed_id") or "")
        request_id = payload.get("request_id")
        version_number = payload.get("version_number")
        if not embed_id or not isinstance(version_number, int) or isinstance(version_number, bool) or version_number < 1:
            logger.warning("Invalid store_embed_diff payload from user %s", user_id)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid embed diff payload"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        if await requires_atomic_project_embed_write(directus_service, embed_id):
            logger.warning(
                "Rejected legacy store_embed_diff for atomic Project embed %s from user %s",
                embed_id,
                user_id,
            )
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Project file revisions require atomic commit"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        encrypted_snapshot = payload.get("encrypted_snapshot")
        encrypted_patch = payload.get("encrypted_patch")
        if (not isinstance(encrypted_snapshot, str) and not isinstance(encrypted_patch, str)) or (
            version_number == 1 and (not isinstance(encrypted_snapshot, str) or encrypted_patch is not None)
        ) or (version_number > 1 and not isinstance(encrypted_patch, str)):
            logger.warning("Rejected unencrypted/empty embed diff row for embed %s", embed_id)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Embed diff row must be encrypted"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        authenticated_user_hash = _user_hash(user_id)
        embed = await directus_service.embed.get_embed_by_id(embed_id)
        if not embed or embed.get("hashed_user_id") != authenticated_user_hash:
            logger.warning(
                "Rejected unauthorized store_embed_diff for embed %s from user %s",
                embed_id,
                user_id,
            )
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Not authorized to store embed diff"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        if embed.get("app_id") == "diagrams" and embed.get("skill_id") == "html" and version_number > 1:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Diagram revisions require atomic commit"}},
                user_id, device_fingerprint_hash,
            )
            return

        row = {
            "embed_id": embed_id,
            "version_number": version_number,
            "encrypted_snapshot": encrypted_snapshot if isinstance(encrypted_snapshot, str) else None,
            "encrypted_patch": encrypted_patch if isinstance(encrypted_patch, str) else None,
            "hashed_user_id": authenticated_user_hash,
            "created_at": int(payload.get("created_at") or 0),
            "has_snapshot": isinstance(encrypted_snapshot, str),
            "has_patch": isinstance(encrypted_patch, str),
        }
        if row["created_at"] <= 0:
            import time

            row["created_at"] = int(time.time())

        transaction_row = {key: row[key] for key in (
            "version_number", "encrypted_snapshot", "encrypted_patch",
        )}
        if payload.get("created_at"):
            transaction_row["created_at"] = row["created_at"]
        try:
            result = await EmbedVersionTransactionService(directus_service).write_legacy_embed_diff(
                embed_id, transaction_row, user_id=user_id,
            )
        except EmbedVersionTransactionError as exc:
            conflict = exc.code in {"immutable_version_mismatch", "ambiguous_history"}
            await manager.send_personal_message({"type": "error", "payload": {
                "message": "Immutable embed version mismatch" if conflict else "Embed history write rejected",
                "code": "embed_diff_conflict" if conflict else "embed_diff_unavailable",
                "request_id": request_id, "embed_id": embed_id, "version_number": version_number,
            }}, user_id, device_fingerprint_hash)
            return
        canonical_digest = result["canonical_digest"]
        if result.get("idempotent"):
            await _send_store_embed_diff_confirmed(manager, user_id, device_fingerprint_hash,
                request_id, embed_id, version_number, canonical_digest)
            return
        logger.info("Stored encrypted embed diff row embed=%s version=%s", embed_id, version_number)

        await manager.broadcast_to_user(
            message={
                "type": "embed_diff_stored",
                "event_for_client": "embed_diff_stored",
                **row,
            },
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,
        )
        await _send_store_embed_diff_confirmed(
            manager,
            user_id,
            device_fingerprint_hash,
            request_id,
            embed_id,
            version_number,
            canonical_digest,
        )
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass
