"""Progress updates of an images.modify result card.

Wire contract (processing updates of the result embed, ``embed_type`` and
content ``type`` ``generated_image``)::

    {"app_id": "images", "skill_id": "modify", "type": "generated_image",
     "status": "processing", "prompt": <instructions>, "model": <author model id>,
     "output_filetype": "png" | "jpg", "input_embed_ids": [...],
     "draft_stage": "writing" | "running" | "checking" | "correcting",
     "draft_attempt": <1-based round>,
     "image_draft": <base64 JPEG, no data: prefix, at most 60 KB>}   # only once a picture was computed

The latest computed picture stays in every later update until the next one
replaces it; the finished content never carries ``image_draft``. Updates are
never stored: only the finished picture is encrypted, uploaded and persisted.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any, Optional, Sequence

from backend.apps.images.modify_author import STAGE_CHECKING, STAGE_CORRECTING, STAGE_RUNNING, STAGE_WRITING
from backend.apps.images.modify_program import reduced_jpeg

logger = logging.getLogger(__name__)

STAGES = (STAGE_WRITING, STAGE_RUNNING, STAGE_CHECKING, STAGE_CORRECTING)
MAX_DRAFT_BASE64_CHARS = 60_000
# Raw JPEG budget so that its base64 text stays within MAX_DRAFT_BASE64_CHARS.
_MAX_DRAFT_JPEG_BYTES = MAX_DRAFT_BASE64_CHARS * 3 // 4
_DRAFT_SIDES = (512, 384, 256)


def encode_draft(draft_jpeg: bytes) -> Optional[str]:
    """Base64 of a draft JPEG within the size budget, shrinking it when needed; ``None`` if impossible."""
    data = draft_jpeg
    for side in _DRAFT_SIDES:
        if len(data) <= _MAX_DRAFT_JPEG_BYTES:
            break
        data = reduced_jpeg(draft_jpeg, side=side, max_bytes=_MAX_DRAFT_JPEG_BYTES)
    if len(data) > _MAX_DRAFT_JPEG_BYTES:
        logger.warning("Modify draft of %d bytes could not be reduced below the budget; sent without picture",
                       len(draft_jpeg))
        return None
    return base64.b64encode(data).decode("ascii")


def processing_content(
    *, instructions: str, model: Optional[str], output_filetype: str, input_embed_ids: Sequence[str],
    stage: str, attempt: int, image_draft: Optional[str],
) -> dict[str, Any]:
    """Content of one processing update (see the module docstring for the contract)."""
    if stage not in STAGES:
        raise ValueError(f"unknown modify progress stage {stage!r}")
    if attempt < 1:
        raise ValueError("modify progress attempts are 1-based")
    content: dict[str, Any] = {
        "app_id": "images", "skill_id": "modify", "type": "generated_image", "status": "processing",
        "prompt": instructions, "model": model, "output_filetype": output_filetype,
        "input_embed_ids": list(input_embed_ids), "draft_stage": stage, "draft_attempt": int(attempt),
    }
    if image_draft:
        content["image_draft"] = image_draft
    return content


class ModifyProgressPublisher:
    """Sends processing updates of the result embed; usable as the author's progress callback."""

    def __init__(self, embed_service: Any, *, embed_id: str, parent_embed_id: str, user_id: str,
                 chat_id: Optional[str], message_id: Optional[str], instructions: str, model: Optional[str],
                 output_filetype: str, input_embed_ids: Sequence[str], log_prefix: str) -> None:
        self._embed_service = embed_service
        self._embed_id = embed_id
        self._parent_embed_id = parent_embed_id
        self._user_id = user_id
        self._user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        self._chat_id = chat_id
        self._message_id = message_id
        self._instructions = instructions
        self._model = model
        self._output_filetype = output_filetype
        self._input_embed_ids = list(input_embed_ids)
        self._log_prefix = log_prefix
        self._draft: Optional[str] = None
        self._last: Optional[tuple[str, int, Optional[str]]] = None

    def set_input_embed_ids(self, input_embed_ids: Sequence[str]) -> None:
        """Show the pictures the program actually runs on (the original inputs of a changed result)."""
        self._input_embed_ids = list(input_embed_ids)

    async def announce(self) -> None:
        """Show the request on the card before anything is computed."""
        await self(STAGE_WRITING, 1, None)

    async def __call__(self, stage: str, attempt: int, draft_jpeg: Optional[bytes]) -> None:
        if draft_jpeg:
            # A newer picture always replaces the shown one; one too large to send shows none.
            self._draft = encode_draft(draft_jpeg)
        state = (stage, attempt, self._draft)
        if state == self._last or not self._chat_id or not self._message_id:
            return
        self._last = state
        from toon_format import encode as toon_encode

        content = processing_content(
            instructions=self._instructions, model=self._model, output_filetype=self._output_filetype,
            input_embed_ids=self._input_embed_ids, stage=stage, attempt=attempt, image_draft=self._draft,
        )
        await self._embed_service.send_embed_data_to_client(
            embed_id=self._embed_id,
            embed_type="generated_image",
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
            app_id="images",
            skill_id="generated_image",
        )
