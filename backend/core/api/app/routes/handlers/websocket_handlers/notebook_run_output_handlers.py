"""
notebook_run_output_handlers.py

Handles encrypted notebook-run output sidecars. The encrypted payload is
client-side encrypted with the notebook embed key; the server stores only
routeable metadata and broadcasts ciphertext to the runner's devices.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, Dict, List
from uuid import uuid4

from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager

if TYPE_CHECKING:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService


logger = logging.getLogger(__name__)

COLLECTION = "notebook_run_outputs"


async def _verify_chat_accessible(directus_service: DirectusService, chat_id: str, user_id: str) -> bool:
    try:
        return bool(await directus_service.chat.check_chat_ownership(chat_id, user_id))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("[notebook_run_outputs] ownership check failed chat=%s user=%s err=%s", chat_id, user_id, exc, exc_info=True)
        return False


async def _verify_notebook_in_chat(cache_service: CacheService, directus_service: DirectusService, chat_id: str, embed_id: str, user_id: str) -> bool:
    try:
        chat_embed_ids = await cache_service.get_chat_embed_ids(chat_id)
        if embed_id in chat_embed_ids:
            return True
        metadata = await directus_service.embed.get_embed_by_id(embed_id)
        if not isinstance(metadata, dict):
            return False
        expected_user_hash = hashlib.sha256(user_id.encode()).hexdigest()
        expected_chat_hash = hashlib.sha256(chat_id.encode()).hexdigest()
        if metadata.get("hashed_user_id") != expected_user_hash or metadata.get("hashed_chat_id") != expected_chat_hash:
            return False
        embed_type = str(metadata.get("type") or metadata.get("backend_type") or "").lower()
        return embed_type in {"notebook", "code-notebook"} or metadata.get("status") == "finished"
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("[notebook_run_outputs] embed/chat check failed chat=%s embed=%s user=%s err=%s", chat_id, embed_id, user_id, exc, exc_info=True)
        return False


async def _load_existing_output(directus_service: DirectusService, chat_id: str, embed_id: str, user_id: str) -> Dict[str, Any]:
    items = await directus_service.get_items(
        COLLECTION,
        params={
            "filter[chat_id][_eq]": chat_id,
            "filter[notebook_embed_id][_eq]": embed_id,
            "filter[author_user_id][_eq]": user_id,
            "sort": "-updated_at",
            "limit": 1,
            "fields": "id,chat_id,notebook_embed_id,author_user_id,source_version,key_version,encrypted_payload,created_at,updated_at",
        },
        admin_required=True,
    ) or []
    return items[0] if items else {}


def _payload_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "chat_id": row.get("chat_id"),
        "notebook_embed_id": row.get("notebook_embed_id"),
        "id": row.get("id"),
        "author_user_id": row.get("author_user_id"),
        "source_version": row.get("source_version"),
        "key_version": row.get("key_version"),
        "encrypted_payload": row.get("encrypted_payload"),
        "created_at": int(row.get("created_at") or row.get("updated_at") or 0),
        "updated_at": int(row.get("updated_at") or row.get("created_at") or 0),
    }


async def _broadcast_output(manager: ConnectionManager, row: Dict[str, Any], user_id: str) -> None:
    await manager.broadcast_to_user(
        {"type": "notebook_run_output_synced", "payload": _payload_from_row(row)},
        user_id,
        exclude_device_hash=None,
    )


async def _impl_upsert(manager, cache_service, directus_service, user_id, device_fingerprint_hash, payload) -> None:
    chat_id = payload.get("chat_id")
    embed_id = payload.get("notebook_embed_id")
    encrypted_payload = payload.get("encrypted_payload")
    created_at = payload.get("created_at")
    updated_at = payload.get("updated_at")
    key_version = payload.get("key_version")
    source_version = payload.get("source_version")

    if not all([chat_id, embed_id, encrypted_payload, created_at is not None, updated_at is not None]):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing fields for upsert_notebook_run_output"}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    if not await _verify_chat_accessible(directus_service, chat_id, user_id):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "You do not have permission to sync this notebook output."}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    if not await _verify_notebook_in_chat(cache_service, directus_service, chat_id, embed_id, user_id):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Notebook output does not belong to this chat."}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    existing = await _load_existing_output(directus_service, chat_id, embed_id, user_id)
    output_id = existing.get("id") or payload.get("id") or str(uuid4())
    row = {
        "id": output_id,
        "chat_id": chat_id,
        "notebook_embed_id": embed_id,
        "author_user_id": user_id,
        "source_version": source_version,
        "key_version": key_version,
        "encrypted_payload": encrypted_payload,
        "created_at": int(existing.get("created_at") or created_at),
        "updated_at": int(updated_at),
    }
    try:
        if existing:
            await directus_service.update_item(
                COLLECTION,
                output_id,
                {
                    "source_version": source_version,
                    "key_version": key_version,
                    "encrypted_payload": encrypted_payload,
                    "updated_at": int(updated_at),
                },
            )
        else:
            await directus_service.create_item(COLLECTION, row, admin_required=True)
    except Exception as exc:
        logger.error("[notebook_run_outputs] upsert failed id=%s err=%s", output_id, exc, exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Failed to save notebook output", "notebook_embed_id": embed_id}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return
    await _broadcast_output(manager, row, user_id)


async def handle_upsert_notebook_run_output(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
) -> None:
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("upsert_notebook_run_output", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        await _impl_upsert(manager, cache_service, directus_service, user_id, device_fingerprint_hash, payload)
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span
                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass


async def handle_request_notebook_run_output(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
) -> None:
    chat_id = payload.get("chat_id")
    embed_id = payload.get("notebook_embed_id")
    if not chat_id or not embed_id:
        return
    if not await _verify_chat_accessible(directus_service, chat_id, user_id):
        return
    if not await _verify_notebook_in_chat(cache_service, directus_service, chat_id, embed_id, user_id):
        return
    row = await _load_existing_output(directus_service, chat_id, embed_id, user_id)
    if row:
        await manager.send_personal_message(
            {"type": "notebook_run_output_synced", "payload": _payload_from_row(row)},
            user_id,
            device_fingerprint_hash,
        )


async def fetch_notebook_run_outputs_for_chats(
    directus_service: DirectusService,
    chat_ids: List[str],
    user_id: str,
) -> List[Dict[str, Any]]:
    if not chat_ids:
        return []
    try:
        rows = await directus_service.get_items(
            COLLECTION,
            params={
                "filter[chat_id][_in]": ",".join(chat_ids),
                "filter[author_user_id][_eq]": user_id,
                "fields": "id,chat_id,notebook_embed_id,author_user_id,source_version,key_version,encrypted_payload,created_at,updated_at",
                "sort": "-updated_at",
                "limit": -1,
            },
            admin_required=True,
        ) or []
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.warning("Failed to fetch notebook outputs for sync: %s", exc, exc_info=True)
        return []
