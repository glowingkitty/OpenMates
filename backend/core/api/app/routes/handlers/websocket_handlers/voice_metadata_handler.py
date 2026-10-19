"""First-party authenticated personal-chat metadata; never public/API-key access."""
import logging
import traceback
from typing import Any

from backend.shared.python_utils import voice_chat_metadata as metadata

logger = logging.getLogger(__name__)


async def handle_voice_metadata(*, manager: Any, cache_service: Any, directus_service: Any,
                                encryption_service: Any, user_id: str, user_id_hash: str,
                                session_hash: str, device_fingerprint_hash: str,
                                message_type: str, payload: Any) -> None:
    auth = dict(manager=manager, cache_service=cache_service, directus_service=directus_service,
                encryption_service=encryption_service, user_id=user_id, user_id_hash=user_id_hash,
                device_fingerprint_hash=device_fingerprint_hash)
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    try:
        if message_type == "voice_metadata_request":
            accepted = await metadata.admit(cache=cache_service, directus=directus_service,
                encryption=encryption_service, user_id=user_id, user_hash=user_id_hash,
                session_id=session_hash, payload=payload)
            await manager.send_personal_message({"type": "voice_metadata_accepted", "payload": {
                "request_id": request_id, "accepted_request_id": accepted}}, user_id, device_fingerprint_hash)
            await metadata.send_pending(**auth, request_id=accepted)
        elif message_type == "voice_metadata_commit":
            result = await metadata.commit(cache=cache_service, directus=directus_service,
                encryption=encryption_service, user_id=user_id, user_hash=user_id_hash, payload=payload)
            await manager.send_personal_message({"type": "voice_metadata_stored", "payload": result}, user_id, device_fingerprint_hash)
            if result["encrypted_metadata"]:
                await manager.broadcast_to_user(message={"type": "encrypted_chat_metadata", "payload": {
                    "chat_id": result["chat_id"], "versions": result["versions"], **result["encrypted_metadata"]}},
                    user_id=user_id, exclude_device_hash=None)
        elif message_type == "voice_metadata_pending":
            # Recovery is free; bound repeated authenticated discovery requests.
            client = await cache_service.client
            import time
            bucket = metadata.key("recovery-rate", user_id, session_hash, str(int(time.time()) // 60))
            count = await client.incr(bucket)
            await client.expire(bucket, 120)
            if count <= 30:
                await metadata.send_pending(**auth)
    except Exception as exc:
        if isinstance(exc, metadata.MetadataStale):
            chat = exc.chat
            await manager.send_personal_message({"type": "encrypted_chat_metadata", "payload": {
                "chat_id": chat["id"], "versions": {"title_v": int(chat.get("title_v") or 0),
                    "metadata_v": max(int(chat.get("metadata_v") or 0), int(chat.get("title_v") or 0))},
                **{field: chat.get(field) for field in ("encrypted_title", "encrypted_chat_summary", "encrypted_chat_key")},
            }}, user_id, device_fingerprint_hash)
        # Report only code locations, never exception text: provider/storage
        # exceptions can contain private request data.
        location = traceback.extract_tb(exc.__traceback__)[-1]
        stage = f"{location.name}:{location.lineno}"
        logger.warning("Voice metadata request unavailable category=%s stage=%s", type(exc).__name__, stage)
        await manager.send_personal_message({"type": "voice_metadata_error", "payload": {
            "request_id": request_id, "code": "metadata_stale" if isinstance(exc, metadata.MetadataStale) else "metadata_unavailable",
            "stage": stage}}, user_id, device_fingerprint_hash)
