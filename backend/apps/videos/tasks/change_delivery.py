"""Store, charge and publish a changed video as version N+1 of the same embed.

Second half of ``generate_change``: safety on the first, middle and last frame
of the changed video, the version check before anything is uploaded or
charged, encrypted storage of the new version (and of a newly generated clip),
its kept record, the file-key union of every version, one charge under
``{embed_id}:v{N}:{change_id}``, and publication through the shared media
revision mechanism (refunded when the server refuses to seal the version).
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from backend.apps.videos.tasks.video_audio import audio_extra, kept_audio
from backend.apps.videos.tasks.video_kept import KeptVideo

logger = logging.getLogger(__name__)

NEW_CLIP = "clip-new"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _credits(made: Any, resolution: str) -> tuple[int, dict[str, Any]]:
    """Everything the change used: added clip seconds, opening still, author calls and the sandbox render."""
    from backend.apps.videos.tasks.generate_billing import add_audio_credits, composed_credits, omni_clip_credits

    credits, details = await composed_credits(usage=made.video.usage, sandbox_seconds=made.video.sandbox_seconds)
    credits, details = add_audio_credits(credits, details, made.video.audio_generated)
    clip_credits = omni_clip_credits(resolution, made.clip_seconds) if made.new_clip else 0
    details = {**details, "added_clip_seconds": made.clip_seconds, "added_clip_credits": clip_credits,
               "opening_still_credits": made.still_credits, "resolution": resolution}
    return credits + clip_credits + made.still_credits, details


def _kept_record(context: Any, made: Any, stored: Any) -> KeptVideo:
    clips = made.clips
    if clips is not None and made.new_clip:
        index = 0 if made.new_clip_at_start else len(clips) - 1
        clips = tuple(dataclasses.replace(clip, stored=stored.object(NEW_CLIP)) if position == index else clip
                      for position, clip in enumerate(clips))
    kept = context.kept
    return KeptVideo(
        version=context.target.next_version, made_by=made.made_by, aspect_ratio=kept.aspect_ratio,
        resolution=kept.resolution, width=made.video.width, height=made.video.height,
        video=stored.object("original"), source=made.video.source if clips is None else None,
        inputs=made.inputs if clips is None else (), clips=clips, audio=kept_audio(stored, made.video.audio),
    )


async def deliver_change(context: Any, made: Any) -> dict[str, Any]:
    from backend.apps.videos.generate_request import OMNI_MODEL
    from backend.apps.videos.tasks.generate_change import ERROR_VERSION_CHANGED, VERSION_CHANGED_MESSAGE, ChangeFailed
    from backend.apps.videos.tasks.generate_pipeline import _charge, _embed_service, check_output_frames
    from backend.apps.videos.tasks.generate_result import (
        MADE_BY_GENERATIVE,
        assistant_result,
        composed_content,
    )
    from backend.apps.videos.tasks.video_kept import remember_video
    from backend.apps.videos.tasks.video_storage import CHATFILES, delete_video_files, index_video, upload_video_files
    from backend.shared.python_utils.media_revision import (
        RevisionPreconditionFailed,
        assert_current_version,
        billing_event_id,
        cache_file_keys,
        finish_published_revision,
        publish_revision,
        refund_refused_revision,
        revision_content_fields,
        revision_result_fields,
    )

    task, target, request, video = context.task, context.target, context.request, made.video
    try:
        await assert_current_version(task._directus_service, target, user_id=context.user_id, chat_id=context.chat_id)
    except RevisionPreconditionFailed as exc:
        raise ChangeFailed(ERROR_VERSION_CHANGED, VERSION_CHANGED_MESSAGE) from exc
    await check_output_frames(
        task, video.mp4, instructions=request.instructions, user_id=context.user_id, message_id=context.message_id,
        source_embed_id=target.embed_id, output_embed_id=target.embed_id, model=video.author_model or None,
        log_prefix=context.log_prefix,
    )
    credits, usage_details = await _credits(made, context.kept.resolution)

    stored = await upload_video_files(
        task, s3_service=context.s3_service, bucket_name=context.bucket, user_id=context.user_id, mp4=video.mp4,
        thumbnail=video.thumbnail_png, thumbnail_format="png", vault_key_id=context.vault_key_id,
        label=f"video_v{target.next_version}",
        extra={**({NEW_CLIP: (made.new_clip, "mp4", "video/mp4")} if made.new_clip else {}),
               **audio_extra(made.video.audio)},
    )
    event_id = billing_event_id(target.embed_id, target.next_version, target.change_id)
    team_id = str(context.arguments["team_id"]) if context.arguments.get("team_id") else None
    user_hash = _hash(context.user_id)
    generative = made.made_by == MADE_BY_GENERATIVE
    billing_status = "not_charged"
    kept_key = None
    try:
        kept_key = await remember_video(task, s3_service=context.s3_service, kept=_kept_record(context, made, stored),
                                        user_id=context.user_id, embed_id=target.embed_id,
                                        vault_key_id=context.vault_key_id)
        union = await cache_file_keys(task, target=target, new_keys=[*stored.file_keys(),
                                                                      {"bucket": CHATFILES, "key": kept_key}])
        billing_status = await _charge(
            context.arguments, user_id=context.user_id, app_id="videos", skill_id="generate", credits=credits,
            usage_details=usage_details,
            model_ref=f"google/{OMNI_MODEL}" if made.new_clip else (video.author_model or "e2b/sandbox"),
            team_id=team_id, duration_seconds=round(video.duration_in_frames / video.fps, 3), event_id=event_id,
            log_prefix=context.log_prefix,
        )
        content = {
            **composed_content(
                skill_id="generate", stored=stored, video=video, instructions=request.instructions,
                input_embed_ids=[], source_titles=[], routing_decided_by="request_mode",
                billing_status=billing_status, version=target.next_version, made_by=made.made_by,
                has_clips=made.clips is not None, model=OMNI_MODEL if generative else None,
                provider="Google Gemini API + E2B" if made.new_clip else "E2B",
            ),
            **revision_content_fields(target),
            "change": request.change,
        }
        await publish_revision(
            _embed_service(task), target=target, content=content, s3_file_keys=union, chat_id=context.chat_id,
            message_id=context.message_id, user_id=context.user_id, user_id_hash=user_hash,
            created_at=int(datetime.now(timezone.utc).timestamp()), log_prefix=context.log_prefix,
        )
    except BaseException:
        # Nothing was published: give the charge back and drop what this attempt uploaded.
        try:
            await refund_refused_revision(
                user_id=context.user_id, user_id_hash=user_hash,
                credits=credits if billing_status == "charged" else 0, app_id="videos", skill_id="generate",
                event_id=event_id, team_id=team_id, log_prefix=context.log_prefix,
                reason="Video change failed before its new version was published", noun="video",
            )
        finally:
            await delete_video_files(context.s3_service, stored)
            if kept_key:
                await context.s3_service.delete_file(CHATFILES, kept_key)
        raise
    await finish_published_revision(task, target=target, index=lambda: index_video(
        task, stored, user_id=context.user_id, embed_id=target.embed_id, mp4=video.mp4,
        provenance={"labeling": "metadata_only", "visual_watermark": False,
                    "provider_watermarking": "SynthID" if generative else "none"},
        log_prefix=context.log_prefix, existing_record_id=target.upload_record_id,
        retained_size_bytes=target.retained_size_bytes,
    ), log_prefix=context.log_prefix)
    logger.info("%s Video %s is now version %d (%s, %d credits)", context.log_prefix, target.embed_id[:8],
                target.next_version, request.change, credits)
    return {**assistant_result(embed_id=target.embed_id, content=content), **revision_result_fields(target)}
