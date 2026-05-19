"""
code_run_output_handlers.py

Handles encrypted Code Run terminal-output sidecars:
  - upsert_code_run_output  → create/update latest output for a code embed
  - request_code_run_output → fetch latest output for an embed on demand

The encrypted_payload is client-side encrypted with the embed key. The server is
blind to terminal output and only enforces chat ownership plus author updates.
"""

import logging
from typing import Any, Dict
from uuid import uuid4

from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)

COLLECTION = "code_run_outputs"


async def _verify_chat_accessible(
    directus_service: DirectusService,
    chat_id: str,
    user_id: str,
) -> bool:
    try:
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if is_owner:
            return True
        metadata = await directus_service.chat.get_chat_metadata(chat_id)
        return metadata is None
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(
            "[code_run_outputs] ownership check failed chat=%s user=%s err=%s",
            chat_id,
            user_id,
            exc,
            exc_info=True,
        )
        return False


async def _load_existing_output(
    directus_service: DirectusService,
    chat_id: str,
    embed_id: str,
    user_id: str,
) -> Dict[str, Any]:
    items = await directus_service.get_items(
        COLLECTION,
        params={
            "filter[chat_id][_eq]": chat_id,
            "filter[embed_id][_eq]": embed_id,
            "filter[author_user_id][_eq]": user_id,
            "sort": "-updated_at",
            "limit": 1,
            "fields": "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
        },
        admin_required=True,
    ) or []
    return items[0] if items else {}


async def _broadcast_output(
    manager: ConnectionManager,
    row: Dict[str, Any],
    user_id: str,
):
    await manager.broadcast_to_user(
        {
            "type": "code_run_output_synced",
            "payload": {
                "chat_id": row.get("chat_id"),
                "embed_id": row.get("embed_id"),
                "id": row.get("id"),
                "author_user_id": row.get("author_user_id"),
                "key_version": row.get("key_version"),
                "encrypted_payload": row.get("encrypted_payload"),
                "created_at": int(row.get("created_at") or row.get("updated_at") or 0),
                "updated_at": int(row.get("updated_at") or row.get("created_at") or 0),
            },
        },
        user_id,
        exclude_device_hash=None,
    )


async def handle_upsert_code_run_output(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,  # noqa: ARG001
    directus_service: DirectusService,
    encryption_service: EncryptionService,  # noqa: ARG001
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
):
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("upsert_code_run_output", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        await _impl_upsert(manager, directus_service, user_id, device_fingerprint_hash, payload)
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span
                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass


async def _impl_upsert(manager, directus_service, user_id, device_fingerprint_hash, payload):
    chat_id = payload.get("chat_id")
    embed_id = payload.get("embed_id")
    encrypted_payload = payload.get("encrypted_payload")
    created_at = payload.get("created_at")
    updated_at = payload.get("updated_at")
    key_version = payload.get("key_version")

    if not all([chat_id, embed_id, encrypted_payload, created_at is not None, updated_at is not None]):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing fields for upsert_code_run_output"}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    if not await _verify_chat_accessible(directus_service, chat_id, user_id):
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "You do not have permission to sync this Code Run output."}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    existing = await _load_existing_output(directus_service, chat_id, embed_id, user_id)
    output_id = existing.get("id") or payload.get("id") or str(uuid4())
    row = {
        "id": output_id,
        "chat_id": chat_id,
        "embed_id": embed_id,
        "author_user_id": user_id,
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
                    "key_version": key_version,
                    "encrypted_payload": encrypted_payload,
                    "updated_at": int(updated_at),
                },
            )
        else:
            await directus_service.create_item(COLLECTION, row, admin_required=True)
    except Exception as exc:
        logger.error("[code_run_outputs] upsert failed id=%s err=%s", output_id, exc, exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Failed to save Code Run output", "embed_id": embed_id}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    await _broadcast_output(manager, row, user_id)
    logger.info("[code_run_outputs] synced embed=%s chat=%s user=%s", embed_id, chat_id, user_id)


async def handle_request_code_run_output(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,  # noqa: ARG001
    directus_service: DirectusService,
    encryption_service: EncryptionService,  # noqa: ARG001
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
):
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("request_code_run_output", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        chat_id = payload.get("chat_id")
        embed_id = payload.get("embed_id")
        if not chat_id or not embed_id:
            return
        if not await _verify_chat_accessible(directus_service, chat_id, user_id):
            return
        row = await _load_existing_output(directus_service, chat_id, embed_id, user_id)
        if row:
            await manager.send_personal_message(
                {
                    "type": "code_run_output_synced",
                    "payload": {
                        "chat_id": row.get("chat_id"),
                        "embed_id": row.get("embed_id"),
                        "id": row.get("id"),
                        "author_user_id": row.get("author_user_id"),
                        "key_version": row.get("key_version"),
                        "encrypted_payload": row.get("encrypted_payload"),
                        "created_at": int(row.get("created_at") or row.get("updated_at") or 0),
                        "updated_at": int(row.get("updated_at") or row.get("created_at") or 0),
                    },
                },
                user_id,
                device_fingerprint_hash,
            )
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span
                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass
