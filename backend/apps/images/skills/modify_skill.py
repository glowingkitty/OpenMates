"""images.modify skill: validate the call and queue it on the shared media worker.

The assistant passes natural-language instructions and one to six exact
embed_refs of pictures in the conversation. The skill resolves every reference
through the conversation's file index (exact match only) and queues one
registered generated-media request; the worker reads the pictures server-side,
so no picture travels through the broker. A call outside the contract returns
an explicit error and nothing is queued or charged.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from backend.apps.base_skill import BaseSkill
from backend.apps.images.modify_request import ModifyRequestError, parse_modify_request
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery

logger = logging.getLogger(__name__)

NOT_IN_CHAT_MESSAGE = (
    "is not a picture in this conversation. Pass the exact embed_ref of an uploaded or generated "
    "image, a vector graphic or an embroidery result shown in this chat."
)


class ModifySkill(BaseSkill):
    """Change or combine pictures from the chat with an exact, model-written editing program."""

    async def execute(
        self,
        instructions: Optional[str] = None,
        images: Optional[list[str]] = None,
        requirements: Optional[list[str]] = None,
        output_filetype: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in images.ModifySkill")
            return {"error": "Picture editing is temporarily unavailable", "error_code": "unavailable"}
        try:
            request = parse_modify_request(
                instructions=instructions, images=images, requirements=requirements,
                output_filetype=output_filetype,
            )
        except ModifyRequestError as exc:
            return {"error": str(exc), "error_code": "invalid_request"}

        file_path_index: dict[str, str] = kwargs.get("file_path_index") or {}
        input_embed_ids: list[str] = []
        for ref in request.images:
            embed_id = file_path_index.get(ref)
            if not embed_id:
                return {"error": f"'{ref}' {NOT_IN_CHAT_MESSAGE}", "error_code": "invalid_input"}
            input_embed_ids.append(embed_id)

        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        embed_id = next((value for value in placeholder_embed_ids if value), str(uuid.uuid4()))
        task_args: dict[str, Any] = {
            "instructions": request.instructions,
            "images": list(request.images),
            "input_embed_ids": input_embed_ids,
            "requirements": list(request.requirements),
            "output_filetype": request.output_filetype,
            "user_id": kwargs.get("user_id"),
            "user_vault_key_id": kwargs.get("user_vault_key_id"),
            "api_key_hash": kwargs.get("api_key_hash"),
            "device_hash": kwargs.get("device_hash"),
            **({"team_id": kwargs["team_id"]} if kwargs.get("team_id") else {}),
            "chat_id": self._current_chat_id,
            "message_id": self._current_message_id,
            "app_id": self.app_id,
            "skill_id": self.skill_id,
            "embed_id": embed_id,
            **({"same_turn_batch_id": kwargs["same_turn_batch_id"]} if kwargs.get("same_turn_batch_id") else {}),
            **({"internal_llm_policy": kwargs["internal_llm_policy"]} if kwargs.get("internal_llm_policy") else {}),
        }
        task_args["requests"] = [{key: value for key, value in task_args.items() if key != "requests"}]
        # Dispatch failures (including RequiredRecoveryOutputError for a turn without
        # output admission) propagate to the skill executor unchanged.
        task_id = await execute_skill_via_celery(
            app_id=self.app_id, skill_id=self.skill_id, arguments=task_args,
            celery_producer=self.celery_producer,
        )
        return {"task_id": task_id, "embed_id": embed_id, "status": "processing"}
