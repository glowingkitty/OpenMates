"""design.embroidery skill: validate the request and enqueue the conversion on the shared media worker.

The assistant passes the exact embed_ref of a vector graphic in the chat. The
skill resolves it to an embed ID through the conversation's file index; the
worker reads the SVG server-side, so no graphic travels through the broker.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.apps.base_skill import BaseSkill
from backend.apps.design.embroidery.content import INVALID_SOURCE_MESSAGE
from backend.apps.design.embroidery.request import parse_embroidery_request
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery

logger = logging.getLogger(__name__)


class EmbroiderySkill(BaseSkill):
    """Turn a vector graphic from the chat into embroidery machine files."""

    async def execute(
        self,
        source: str | None = None,
        width_mm: float | None = None,
        hoop: str | None = None,
        fabric: str | None = None,
        instructions: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in design.EmbroiderySkill")
            return {"error": "Embroidery conversion is temporarily unavailable"}
        try:
            request = parse_embroidery_request(
                width_mm=width_mm, hoop=hoop, fabric=fabric, instructions=instructions,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        source_ref = (source or "").strip()
        if not source_ref:
            return {"error": "source is required: " + INVALID_SOURCE_MESSAGE, "error_code": "invalid_source"}
        file_path_index: dict[str, str] = kwargs.get("file_path_index") or {}
        source_embed_id = file_path_index.get(source_ref)
        if not source_embed_id:
            return {
                "error": f"'{source_ref}' is not a graphic in this conversation. {INVALID_SOURCE_MESSAGE}",
                "error_code": "invalid_source",
            }

        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        embed_id = next((value for value in placeholder_embed_ids if value), str(uuid.uuid4()))
        task_args: dict[str, Any] = {
            "source": source_ref,
            "source_embed_id": source_embed_id,
            "width_mm": request.width_mm,
            "hoop": request.hoop,
            "fabric": request.fabric,
            "instructions": request.instructions,
            "input_embed_ids": [source_embed_id],
            "user_id": kwargs.get("user_id"),
            "user_vault_key_id": kwargs.get("user_vault_key_id"),
            "api_key_hash": kwargs.get("api_key_hash"),
            "device_hash": kwargs.get("device_hash"),
            "chat_id": self._current_chat_id,
            "message_id": self._current_message_id,
            "app_id": self.app_id,
            "skill_id": self.skill_id,
            "embed_id": embed_id,
            **({"same_turn_batch_id": kwargs["same_turn_batch_id"]} if kwargs.get("same_turn_batch_id") else {}),
        }
        task_args["requests"] = [{key: value for key, value in task_args.items() if key != "requests"}]
        # Dispatch failures (including RequiredRecoveryOutputError for a turn
        # without output admission) propagate to the skill executor unchanged.
        task_id = await execute_skill_via_celery(
            app_id=self.app_id, skill_id=self.skill_id, arguments=task_args,
            celery_producer=self.celery_producer,
        )
        return {"task_id": task_id, "embed_id": embed_id, "status": "processing"}
