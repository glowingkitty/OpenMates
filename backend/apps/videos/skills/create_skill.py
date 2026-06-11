# backend/apps/videos/skills/create_skill.py
#
# Deterministic Remotion video creation skill.
# Dispatches code-backed Remotion renders to the videos Celery worker and
# returns processing embed IDs immediately for chat and REST clients.

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Optional

from backend.apps.ai.utils.remotion_fences import normalize_remotion_filename
from backend.apps.base_skill import BaseSkill


logger = logging.getLogger(__name__)


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CreateSkill(BaseSkill):
    """Create deterministic videos from Remotion TSX source."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        filename = normalize_remotion_filename(request.get("filename"))
        source = str(request.get("source") or "")
        return {
            "filename": filename,
            "source_preview": source[:240],
        }

    async def execute(
        self,
        source: str,
        filename: Optional[str] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        placeholder_embed_ids: Optional[List[str]] = None,
        user_vault_key_id: Optional[str] = None,
        external_request: bool = False,
        **_: Any,
    ) -> Dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in videos.CreateSkill")
            return {"error": "Remotion video creation service temporarily unavailable"}

        remotion_source = str(source or "").strip()
        if not remotion_source:
            return {"error": "Remotion source is required"}

        embed_id = (
            placeholder_embed_ids[0]
            if placeholder_embed_ids and placeholder_embed_ids[0]
            else str(uuid.uuid4())
        )
        render_id = str(uuid.uuid4())
        normalized_filename = normalize_remotion_filename(filename)
        task_args = {
            "embed_id": embed_id,
            "chat_id": chat_id or self._current_chat_id,
            "message_id": message_id or self._current_message_id,
            "user_id": user_id or "",
            "user_id_hash": _hash_value(user_id or "") if user_id else "",
            "vault_key_id": user_vault_key_id or "",
            "remotion_source": remotion_source,
            "filename": normalized_filename,
            "source_version": 1,
            "auto_started": True,
            "render_id": render_id,
            "external_request": external_request,
        }

        try:
            task_signature = self.celery_producer.send_task(
                "apps.videos.tasks.render_remotion",
                args=[task_args],
                queue="app_videos",
            )
        except Exception as exc:
            logger.error("Failed to dispatch Remotion render task: %s", exc, exc_info=True)
            return {"error": f"Failed to start Remotion render: {exc}"}

        return {
            "task_id": task_signature.id,
            "render_id": render_id,
            "embed_id": embed_id,
            "status": "rendering",
            "filename": normalized_filename,
        }
