"""Finalize the chat's parent app_skill_use card of a cloud terminal command.

main_processor publishes the parent placeholder of an async skill as
"processing" and expects the worker to close it. A cloud command's output lives
in the child terminal code embed; the parent finishes (or errors) when the run
ends. Spec: code-run.cloud.commands.
"""
from __future__ import annotations

import time
from typing import Any

from toon_format import encode as toon_encode


def build_command_parent_content(payload: dict[str, Any], final_status: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the terminal status and the card content for the finished run."""
    command_run = payload["command_run"]
    status = "finished" if final_status.get("status") == "finished" else "error"
    child_id = payload.get("target_embed_id")
    content: dict[str, Any] = {
        "app_id": "code",
        "skill_id": "run",
        "status": status,
        "argv": list(command_run.get("argv") or []),
        "cwd": command_run.get("cwd"),
        "exit_code": final_status.get("exit_code"),
        "result_count": 1 if child_id else 0,
        "embed_ids": [child_id] if child_id else [],
    }
    if status == "error":
        content["error"] = str(final_status.get("error") or final_status.get("status") or "failed")
    return status, content


async def finalize_command_parent_embed(
    payload: dict[str, Any], final_status: dict[str, Any], cache_service: Any,
) -> bool:
    """Set the parent placeholder to finished/error; False when the run had no placeholder."""
    parent_id = (payload.get("command_run") or {}).get("parent_embed_id")
    chat_id, message_id = payload.get("chat_id"), payload.get("message_id")
    user_id, user_id_hash = payload.get("user_id"), payload.get("user_id_hash")
    if not (parent_id and chat_id and message_id and user_id and user_id_hash):
        return False
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.core.api.app.utils.encryption import EncryptionService

    encryption_service = EncryptionService(cache_service=cache_service)
    await encryption_service.initialize()
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    embed_service = EmbedService(
        cache_service=cache_service, directus_service=directus_service, encryption_service=encryption_service,
    )
    status, content = build_command_parent_content(payload, final_status)
    now = int(time.time())
    await embed_service.send_embed_data_to_client(
        embed_id=str(parent_id), embed_type="app_skill_use", content_toon=toon_encode(content),
        chat_id=str(chat_id), message_id=str(message_id), user_id=str(user_id),
        user_id_hash=str(user_id_hash), status=status, encryption_mode="client",
        created_at=now, updated_at=now, embed_ids=content["embed_ids"],
        log_prefix="[CloudCommandParent]", check_cache_status=False,
    )
    return True
