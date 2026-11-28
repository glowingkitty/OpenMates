"""Publish a verified Design as a client-side encrypted chat artifact."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from backend.apps.design.scene import DesignScene
from backend.core.api.app.services.embed_service import EmbedService


async def deliver_design(
    result: dict[str, Any], *, service: EmbedService, chat_id: str, message_id: str,
    user_id: str, user_id_hash: str, task_id: str,
) -> tuple[dict[str, Any], str | None]:
    """Return only content-free status to the conversation model."""
    if result.get("success") is not True:
        return {"status": "error", "error": result.get("error") or "design_author_failed"}, None
    try:
        scene = DesignScene.model_validate_json(result["scene_json"])
    except (KeyError, TypeError, ValidationError):
        return {"status": "error", "error": "design_scene_invalid"}, None

    proposal = result.get("source_embed_id")
    content = scene.wire_json()
    if proposal is not None:
        base_version = result.get("base_version")
        try:
            target = UUID(proposal)
        except (TypeError, ValueError, AttributeError):
            return {"status": "error", "error": "design_scene_invalid"}, None
        if not target.int or type(base_version) is not int or base_version < 1:
            return {"status": "error", "error": "design_scene_invalid"}, None
        snapshot = scene.model_dump(by_alias=True, exclude_none=True)
        snapshot["proposal"] = {"embedId": str(target), "baseVersion": base_version}
        content = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))

    # Personal chat roots use ordinary IDs. UUIDv5 is reserved for other authorities.
    embed_id = str(uuid4())
    sent = await service.send_embed_data_to_client(
        embed_id=embed_id, embed_type="design-document", content_toon=content,
        chat_id=chat_id, message_id=message_id, user_id=user_id, user_id_hash=user_id_hash,
        app_id="design", skill_id="document", task_id=task_id, version_number=1,
        encryption_mode="client", check_cache_status=False,
    )
    if not sent:
        return {"status": "error", "error": "design_delivery_failed"}, None
    reference = json.dumps({"type": "design-document", "embed_id": embed_id})
    summary = {
        "status": "finished",
        "message": (
            "A proposed revision is already attached. The user can open it to preview and apply the changes."
            if proposal else "The editable Design card is already attached to this reply."
        ),
        "reply_instruction": "Confirm in plain language. The card is already rendered. Do not emit another embed or link.",
        "pages": len(scene.pages),
        "attempts": result.get("attempts"),
        "elapsed_ms": result.get("elapsed_ms"),
        "credits_charged": result.get("credits_charged"),
    }
    return summary, reference
