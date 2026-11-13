"""Progress updates of a videos.generate result card.

Wire contract (processing updates of the result child, ``embed_type`` and
content ``type`` ``generated_video``)::

    {"app_id": "videos", "skill_id": "generate", "type": "generated_video",
     "status": "processing", "prompt": <instructions>, "input_embed_ids": [...],
     "progress_stage": "deciding" | "writing" | "rendering" | "correcting" | "generating" | "audio",
     "progress_attempt": <1-based round>}

The stage ``audio`` (sound of a composed video is being generated) adds ``"progress_audio": [kinds]``, a
subset of ``speech``, ``sound``, ``music`` in that order: the kinds generated in this round. It is published once
before the clips are generated and skipped when every clip was already generated earlier.

A change of an earlier video (``generate_change``) adds two fields, so the card
of the change call shows what is being changed: ``"change": "edit" | "extend_start" |
"extend_end"`` and ``"source_embed_id"``, the embed id of the video being
changed (the web client resolves the thumbnail from its own copy of that
embed; no keys, file keys or URLs are ever sent). ``prompt`` is then the change
instruction. The first update is sent before any model call (``deciding``),
``generating`` while a new clip is made (extend), ``writing``/``correcting``
while the author model rewrites a composed video, ``rendering`` while the
sandbox renders (also the join render of an extended clip).

``deciding`` while the route is chosen, ``generating`` while a generative
model makes the clip, ``writing``/``rendering``/``correcting`` while a composed
video is authored and rendered. Updates are never stored; only the finished
(or failed) child is persisted.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

STAGE_DECIDING = "deciding"
STAGE_WRITING = "writing"
STAGE_RENDERING = "rendering"
STAGE_CORRECTING = "correcting"
STAGE_GENERATING = "generating"
STAGE_AUDIO = "audio"
STAGES = (STAGE_DECIDING, STAGE_WRITING, STAGE_RENDERING, STAGE_CORRECTING, STAGE_GENERATING, STAGE_AUDIO)
AUDIO_KINDS = ("speech", "sound", "music")


def processing_content(*, skill_id: str, instructions: str, input_embed_ids: Sequence[str], stage: str,
                       attempt: int, change: Optional[str] = None, source_embed_id: Optional[str] = None,
                       audio: Optional[Sequence[str]] = None) -> dict[str, Any]:
    """Content of one processing update (see the module docstring for the contract)."""
    if stage not in STAGES:
        raise ValueError(f"unknown video progress stage {stage!r}")
    if attempt < 1:
        raise ValueError("video progress attempts are 1-based")
    if (change is None) != (source_embed_id is None):
        raise ValueError("a change progress update needs both the change and the source embed id")
    if (stage == STAGE_AUDIO) != (audio is not None):
        raise ValueError("only the audio stage carries the audio kinds, and it always does")
    content: dict[str, Any] = {
        "app_id": "videos", "skill_id": skill_id, "type": "generated_video", "status": "processing",
        "prompt": instructions, "input_embed_ids": list(input_embed_ids), "progress_stage": stage,
        "progress_attempt": int(attempt),
    }
    if audio is not None:
        unknown = [kind for kind in audio if kind not in AUDIO_KINDS]
        if unknown or not audio:
            raise ValueError(f"unknown or empty audio kinds {list(audio)!r}")
        content["progress_audio"] = [kind for kind in AUDIO_KINDS if kind in audio]
    if change is not None:
        content["change"] = change
        content["source_embed_id"] = source_embed_id
    return content


class VideoProgressPublisher:
    """Sends processing updates of the result child; ``on_stage`` is the composer's stage callback."""

    def __init__(self, embed_service: Any, *, skill_id: str, embed_id: str, parent_embed_id: str, user_id: str,
                 chat_id: Optional[str], message_id: Optional[str], instructions: str,
                 input_embed_ids: Sequence[str], log_prefix: str) -> None:
        self._embed_service = embed_service
        self._skill_id = skill_id
        self._embed_id = embed_id
        self._parent_embed_id = parent_embed_id
        self._user_id = user_id
        self._user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        self._chat_id = chat_id
        self._message_id = message_id
        self._instructions = instructions
        self._input_embed_ids = list(input_embed_ids)
        self._log_prefix = log_prefix
        self._change: Optional[str] = None
        self._source_embed_id: Optional[str] = None
        self._last: Optional[tuple[str, int, tuple[str, ...]]] = None
        self._rounds = 0
        self.stages: list[str] = []

    def mark_change(self, change: str, source_embed_id: str) -> None:
        """Make every later update carry the change kind and the embed id of the video being changed."""
        self._change = change
        self._source_embed_id = source_embed_id

    async def __call__(self, stage: str, attempt: Optional[int] = None,
                       audio: Optional[Sequence[str]] = None) -> None:
        if stage in (STAGE_WRITING, STAGE_CORRECTING):
            self._rounds += 1
        round_number = attempt if attempt is not None else max(1, self._rounds)
        state = (stage, round_number, tuple(audio or ()))
        if state == self._last:
            return
        self._last = state
        self.stages.append(stage)
        if not self._chat_id or not self._message_id:
            return
        from toon_format import encode as toon_encode

        content = processing_content(skill_id=self._skill_id, instructions=self._instructions,
                                     input_embed_ids=self._input_embed_ids, stage=stage, attempt=round_number,
                                     change=self._change, source_embed_id=self._source_embed_id, audio=audio)
        await self._embed_service.send_embed_data_to_client(
            embed_id=self._embed_id,
            embed_type="generated_video",
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
            app_id="videos",
            skill_id="generated_video",
        )

    async def on_stage(self, stage: str) -> None:
        """Stage callback of ``compose_video`` ("writing" | "rendering" | "correcting")."""
        await self(stage)

    async def on_audio(self, kinds: Sequence[str]) -> None:
        """Audio callback of ``compose_video``: the kinds about to be generated in this round."""
        await self(STAGE_AUDIO, audio=kinds)
