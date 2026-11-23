"""Progress updates of a design.embroidery result card (TASK-1610).

Wire contract (processing updates of the result child, ``embed_type`` and
content ``type`` ``embroidery_design``)::

    {"app_id": "design", "skill_id": "embroidery", "type": "embroidery_design",
     "status": "processing", "prompt": <instructions or design name>,
     "input_embed_ids": [<source graphic>],
     "progress_stage": "reading" | "checking" | "adjusting" | "stitching" | "saving"}

The first update (``reading``) is sent before the source graphic is read, so the
card shows the input graphic right away. ``checking`` while the design is
checked for embroidery, ``adjusting`` while a model reworks it, ``stitching``
while the converter creates the stitches, machine files and preview, ``saving``
while the files are encrypted and stored. Updates are never stored; only the
finished (or failed) child is persisted. No keys, file keys or URLs are sent.

Web: frontend/packages/ui/src/components/embeds/design/embroideryProgress.ts
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

STAGE_READING = "reading"
STAGE_CHECKING = "checking"
STAGE_ADJUSTING = "adjusting"
STAGE_STITCHING = "stitching"
STAGE_SAVING = "saving"
STAGES = (STAGE_READING, STAGE_CHECKING, STAGE_ADJUSTING, STAGE_STITCHING, STAGE_SAVING)
CHILD_TYPE = "embroidery_design"


def processing_content(*, skill_id: str, prompt: str, input_embed_ids: Sequence[str], stage: str) -> dict[str, Any]:
    """Content of one processing update (see the module docstring for the contract)."""
    if stage not in STAGES:
        raise ValueError(f"unknown embroidery progress stage {stage!r}")
    return {
        "app_id": "design", "skill_id": skill_id, "type": CHILD_TYPE, "status": "processing",
        "prompt": prompt, "input_embed_ids": [value for value in input_embed_ids if value],
        "progress_stage": stage,
    }


class EmbroideryProgressPublisher:
    """Sends processing updates of the result child; each stage is sent once, in call order."""

    def __init__(self, embed_service: Any, *, skill_id: str, embed_id: str, parent_embed_id: str, user_id: str,
                 chat_id: Optional[str], message_id: Optional[str], prompt: str,
                 input_embed_ids: Sequence[str], log_prefix: str) -> None:
        self._embed_service = embed_service
        self._skill_id = skill_id
        self._embed_id = embed_id
        self._parent_embed_id = parent_embed_id
        self._user_id = user_id
        self._user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        self._chat_id = chat_id
        self._message_id = message_id
        self._prompt = prompt
        self._input_embed_ids = list(input_embed_ids)
        self._log_prefix = log_prefix
        self.stages: list[str] = []

    async def __call__(self, stage: str) -> None:
        if self.stages and self.stages[-1] == stage:
            return
        content = processing_content(skill_id=self._skill_id, prompt=self._prompt,
                                     input_embed_ids=self._input_embed_ids, stage=stage)
        self.stages.append(stage)
        if not self._chat_id or not self._message_id:
            return
        from toon_format import encode as toon_encode

        await self._embed_service.send_embed_data_to_client(
            embed_id=self._embed_id,
            embed_type=CHILD_TYPE,
            content_toon=toon_encode(content),
            chat_id=self._chat_id,
            message_id=self._message_id,
            user_id=self._user_id,
            user_id_hash=self._user_id_hash,
            status="processing",
            encryption_mode="client",
            parent_embed_id=self._parent_embed_id if self._parent_embed_id != self._embed_id else None,
            log_prefix=self._log_prefix,
            check_cache_status=False,
            app_id="design",
            skill_id=CHILD_TYPE,
        )
