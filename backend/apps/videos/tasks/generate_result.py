"""Storage and content of a videos.generate result child.

Every result is ONE ``generated_video`` child of the skill-use parent. Shared
fields of both routes (assertion videos-generate.result.content)::

    made_by ("generative" | "composed"), timeline, fps, width, height,
    duration_seconds, version (1), routing_decided_by ("request_mode" |
    "routing_model"), source_titles, input_embed_ids, files.original
    (+ files.thumbnail), can_extend_end / can_extend_start (generative videos made of clips)

A composed result also carries ``remotion_source``, ``filename``, ``attempts``
and ``author_model``. The MP4 and its PNG thumbnail are encrypted with one AES
key, uploaded to chatfiles and indexed in the owner's generated-asset index,
like a generative clip (``video_storage``).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.apps.videos.tasks.video_storage import StoredVideo, delete_video_files, index_video, \
    upload_video_files

logger = logging.getLogger(__name__)

MADE_BY_GENERATIVE = "generative"
MADE_BY_COMPOSED = "composed"
TIMELINE_FPS = 30
MAX_EXTENDABLE_SECONDS = 60  # an extension needs room for at least 3 more seconds inside the 60 s limit
_RESOLUTION_SHORT_SIDE = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}
ASSISTANT_FIELDS = (
    "prompt", "made_by", "routing_decided_by", "model", "provider", "author_model", "duration_seconds",
    "aspect_ratio", "resolution", "width", "height", "fps", "filename", "attempts", "source_titles",
    "input_embed_ids", "version", "billing_status", "generated_at",
)
COMPOSED_PROVENANCE = {
    "ai_generated": True,
    "labeling": "metadata_only",
    "visual_watermark": False,
    "provider_watermarking": "not_applicable",
    "renderer": "code",
}


def _ratio(aspect_ratio: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in str(aspect_ratio).split(":", 1))
    except ValueError as exc:
        raise ValueError(f"invalid aspect ratio {aspect_ratio!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid aspect ratio {aspect_ratio!r}")
    return width, height


def frame_size(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    """Nominal pixel size of a generative clip (even sides), e.g. 720p 16:9 → 1280×720."""
    short = _RESOLUTION_SHORT_SIDE.get(resolution)
    if short is None:
        raise ValueError(f"unknown video resolution {resolution!r}")
    ratio_w, ratio_h = _ratio(aspect_ratio)
    if ratio_w >= ratio_h:
        width, height = short * ratio_w / ratio_h, short
    else:
        width, height = short, short * ratio_h / ratio_w
    return int(round(width / 2)) * 2, int(round(height / 2)) * 2


def one_clip_timeline(*, duration_seconds: float, width: int, height: int, label: str) -> dict[str, Any]:
    """Timeline of a generative clip: one video track with one part over the whole clip."""
    frames = max(1, int(math.ceil(float(duration_seconds) * TIMELINE_FPS - 1e-6)))
    return {
        "fps": TIMELINE_FPS,
        "duration_in_frames": frames,
        "width": width,
        "height": height,
        "tracks": [{
            "id": "clip-track",
            "name": "Clip",
            "kind": "video",
            "parts": [{
                "id": "clip-1",
                "label": " ".join(label.split())[:80] or "Clip",
                "from": 0,
                "duration_in_frames": frames,
                "kind": "video_clip",
                "texts": [],
            }],
        }],
    }


def extension_flags(*, made_by: str = MADE_BY_COMPOSED, duration_seconds: float = 0.0,
                    has_clips: bool = False) -> dict[str, bool]:
    """Whether the timeline offers extending: generative videos made of clips up to 60 s, while revisions are on."""
    from backend.shared.python_utils.media_revision import revisions_enabled

    can_extend = (made_by == MADE_BY_GENERATIVE and has_clips and duration_seconds < MAX_EXTENDABLE_SECONDS
                  and revisions_enabled())
    return {"can_extend_end": can_extend, "can_extend_start": can_extend}


def aspect_ratio_of(width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


async def store_composed_video(
    task: Any, *, s3_service: Any, bucket_name: str, user_id: str, embed_id: str, mp4: bytes, thumbnail_png: bytes,
    vault_key_id: str, filename: str, log_prefix: str, inputs: Sequence[Any] = (),
) -> StoredVideo:
    """Encrypt, upload and index the MP4, its thumbnail and copies of the input pictures (kept for changes).

    ``filename`` is the composition file name (shown on the result); uploaded
    objects are removed when a later step fails.
    """
    extra = {f"input-{index}": (item.content, item.name.rsplit(".", 1)[-1], item.mime_type)
             for index, item in enumerate(inputs, start=1)}
    stored = await upload_video_files(
        task, s3_service=s3_service, bucket_name=bucket_name, user_id=user_id, mp4=mp4, thumbnail=thumbnail_png,
        thumbnail_format="png", vault_key_id=vault_key_id, label="composed", extra=extra,
    )
    try:
        indexed = await index_video(task, stored, user_id=user_id, embed_id=embed_id, mp4=mp4,
                                    provenance={key: COMPOSED_PROVENANCE[key] for key in
                                                ("labeling", "visual_watermark", "renderer")},
                                    log_prefix=log_prefix)
        if not indexed:
            raise RuntimeError("Failed to index the composed video in account storage")
    except BaseException:
        await delete_video_files(s3_service, stored)
        raise
    logger.info("%s Stored composed video %s (%s)", log_prefix, embed_id[:8], filename)
    return stored


def composed_content(
    *, skill_id: str, stored: StoredVideo, video: Any, instructions: str, input_embed_ids: Sequence[str],
    source_titles: Sequence[str], routing_decided_by: str, billing_status: str, version: int = 1,
    made_by: str = MADE_BY_COMPOSED, has_clips: bool = False, model: str | None = None, provider: str = "E2B",
) -> dict[str, Any]:
    """Content of a finished result child rendered in the sandbox (composed, or joined/trimmed clips)."""
    duration_seconds = round(video.duration_in_frames / video.fps, 3)
    return {
        "app_id": "videos",
        "skill_id": skill_id,
        "type": "video",
        "status": "finished",
        "prompt": instructions,
        "made_by": made_by,
        "routing_decided_by": routing_decided_by,
        "version": version,
        "timeline": video.timeline,
        "fps": video.fps,
        "width": video.width,
        "height": video.height,
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio_of(video.width, video.height),
        "remotion_source": video.source,
        "filename": video.filename,
        "attempts": video.attempts,
        "author_model": video.author_model,
        "model": model if model is not None else (video.author_model.split("/")[-1] if video.author_model else ""),
        "provider": provider,
        "source_titles": list(source_titles),
        "input_embed_ids": list(input_embed_ids),
        "files": stored.files_metadata,
        "s3_base_url": stored.s3_base_url,
        "aes_key": stored.aes_key_b64,
        "aes_nonce": stored.nonce_b64,
        "vault_wrapped_aes_key": stored.vault_wrapped_aes_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "billing_status": billing_status,
        **extension_flags(made_by=made_by, duration_seconds=duration_seconds, has_clips=has_clips),
        "provenance": dict(COMPOSED_PROVENANCE),
    }


def failed_content(*, skill_id: str, instructions: str, input_embed_ids: Sequence[str], error_code: str,
                   user_message: str, made_by: str | None, routing_decided_by: str | None) -> dict[str, Any]:
    """A failed result child: the reason in plain words, no video and no charge."""
    return {
        "app_id": "videos",
        "skill_id": skill_id,
        "type": "video",
        "status": "error",
        "prompt": instructions,
        **({"made_by": made_by} if made_by else {}),
        **({"routing_decided_by": routing_decided_by} if routing_decided_by else {}),
        "input_embed_ids": list(input_embed_ids),
        "files": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "billing_status": "not_charged",
        "error": user_message,
        "error_code": error_code,
    }


def assistant_result(*, embed_id: str, content: Mapping[str, Any]) -> dict[str, Any]:
    """Task result for the batch and the assistant: what was made and how, never keys or the source."""
    from backend.shared.python_utils.generated_media_graph import generated_media_embed_ref

    files = content.get("files") or {}
    return {
        "embed_id": embed_id,
        "child_embed_id": embed_id,
        "child_embed_ids": [embed_id],
        "embed_ref": generated_media_embed_ref("videos", embed_id),
        "type": "video",
        "status": "finished",
        **{key: content[key] for key in ASSISTANT_FIELDS if key in content},
        "files": {variant: {"size_bytes": meta.get("size_bytes"), "format": meta.get("format")}
                  for variant, meta in files.items()},
    }
