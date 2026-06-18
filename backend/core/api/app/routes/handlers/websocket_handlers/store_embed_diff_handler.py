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

logger = logging.getLogger(__name__)


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


async def _read_existing_row(
    directus_service: DirectusService,
    embed_id: str,
    version_number: int,
    hashed_user_id: str,
) -> Dict[str, Any] | None:
    params = {
        "filter": {
            "embed_id": {"_eq": embed_id},
            "version_number": {"_eq": version_number},
            "hashed_user_id": {"_eq": hashed_user_id},
        },
        "limit": 1,
    }
    if hasattr(directus_service, "read_items"):
        rows = await directus_service.read_items("embed_diffs", params=params)
    else:
        rows = await directus_service.get_items("embed_diffs", params=params)
    return (rows or [None])[0]


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
        version_number = payload.get("version_number")
        if not embed_id or not isinstance(version_number, int):
            logger.warning("Invalid store_embed_diff payload from user %s", user_id)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid embed diff payload"}},
                user_id,
                device_fingerprint_hash,
            )
            return

        encrypted_snapshot = payload.get("encrypted_snapshot")
        encrypted_patch = payload.get("encrypted_patch")
        if not isinstance(encrypted_snapshot, str) and not isinstance(encrypted_patch, str):
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

        existing = await _read_existing_row(
            directus_service,
            embed_id,
            version_number,
            authenticated_user_hash,
        )
        if existing:
            logger.debug("Embed diff row already exists: embed=%s version=%s", embed_id, version_number)
            return

        row = {
            "embed_id": embed_id,
            "version_number": version_number,
            "encrypted_snapshot": encrypted_snapshot if isinstance(encrypted_snapshot, str) else None,
            "encrypted_patch": encrypted_patch if isinstance(encrypted_patch, str) else None,
            "hashed_user_id": authenticated_user_hash,
            "created_at": int(payload.get("created_at") or 0),
        }
        if row["created_at"] <= 0:
            import time

            row["created_at"] = int(time.time())

        await directus_service.create_item("embed_diffs", row)
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
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass
