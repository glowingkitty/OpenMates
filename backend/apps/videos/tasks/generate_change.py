"""Changing an earlier videos.generate result: the next version of the same embed.

Assertions videos-generate.change.same-video-next-version, .change.extend-generated-clip,
.change.edit-mode and .billing.metered. A request with ``source_video`` and
``change`` reads the kept record of the video's current version (video_kept)
and makes version N+1 of the same result child through the shared media
revision mechanism (``backend/shared/python_utils/media_revision.py``, the one
images.generate uses):

- ``edit`` of a composed video: the author model gets the kept composition and
  the kept copies of the original pictures, and renders again from them; the kept
  audio clips are offered for reuse by content hash, so only new or changed clips are
  generated and billed (a composed video is never trimmed by code, so its sound
  always goes through this path);
- ``edit`` of a video made of generated clips: structured trims and removals
  are applied by code and rendered as a clip join (no author call, see
  change_edits); any other edit goes to the author with the clip join as its
  starting composition and the clips as ``video_clip`` inputs;
- ``extend_end``: one Gemini Omni clip whose first frame is the video's last
  frame, joined after the video;
- ``extend_start``: an opening still made from the video's first frame, then a
  Gemini Omni clip from that still to the video's first frame, joined before it.

Before anything is paid the video must be a generated video of this chat with
a kept record; a lost race (the video moved to another version) is detected
before the charge. The change is charged once under ``{embed_id}:v{N}:{change_id}``
for exactly what it used; a version the server refuses to seal is refunded. A
failed change publishes nothing on the video, so it keeps its current version.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from backend.apps.videos.generate_request import EXTEND_MAX_SECONDS, GENERATIVE_DEFAULT_SECONDS, GenerateRequest
from backend.apps.videos.tasks.change_edits import ClipEditError, apply_clip_edits, clip_frames, visible_seconds
from backend.apps.videos.tasks.generate_progress import (
    STAGE_DECIDING,
    STAGE_GENERATING,
    STAGE_RENDERING,
    VideoProgressPublisher,
)
from backend.apps.videos.tasks.video_kept import KeptClip, KeptInput, KeptVideo, KeptVideoError

logger = logging.getLogger(__name__)

CHANGE_EDIT, CHANGE_EXTEND_END, CHANGE_EXTEND_START = "edit", "extend_end", "extend_start"
ERROR_CHANGE_NOT_AVAILABLE = "change_not_available"
ERROR_CHANGE_UNAVAILABLE = "change_unavailable"
ERROR_VERSION_CHANGED = "version_changed"
ERROR_INVALID_INPUT = "invalid_input"
ERROR_SAFETY = "safety_rejected"
ERROR_PROVIDER = "provider_unavailable"
ERROR_CREDITS = "insufficient_credits"
MAX_JOINED_SECONDS = 60
OPENING_STILL_MODEL = "gemini-nano-banana-2.1"
OPENING_STILL_CREDITS = 63  # backend/providers/google.yml pricing.per_unit.credits of the still model
CHANGE_NOT_AVAILABLE_MESSAGE = (
    "Changing or extending an existing video is not available right now, so nothing was made or charged. "
    "Describe the whole new video instead to make a new one."
)
NOT_CHANGEABLE_MESSAGE = ("This video cannot be changed: only a video made by this chat can be changed. "
                          "Nothing was made or charged.")
NOT_KEPT_MESSAGE = ("This video was made before videos could be changed, so it cannot be changed. "
                    "Describe the whole new video to make a new one. Nothing was charged.")
VERSION_CHANGED_MESSAGE = "The video changed while this change was made, so nothing was charged. Try again."
EXTEND_COMPOSED_MESSAGE = ("Only a video made of generated clips can be extended. Describe the change instead. "
                           "Nothing was made or charged.")
SAFETY_MESSAGE = "This video change couldn't be made."
PROVIDER_MESSAGE = "The video model is not available right now, so nothing was made or charged."
CREDITS_MESSAGE = "There are not enough credits to change this video."
CONTINUE_LINE = ("Continue seamlessly from the given first frame, which is the last frame of the existing video: "
                 "same scene, characters, style, lighting and camera.")
LEAD_IN_LINE = ("Start from the given first frame and end exactly on the given last frame, which is the first frame "
                "of the existing video: same scene, characters, style, lighting and camera.")
STILL_LINE = ("An opening picture shown just before the given picture, in the same scene, style, lighting and "
              "format, as the start of: ")


class ChangeFailed(RuntimeError):
    """An expected failure of a change: the video keeps its version and nothing is charged."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


ChangeNotAvailable = ChangeFailed  # the pipeline's name for every failed change


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Made:
    """What one change produced, before it is stored."""

    def __init__(self, *, video: Any, made_by: str, clips: Optional[tuple[KeptClip, ...]],
                 inputs: tuple[KeptInput, ...], new_clip: Optional[bytes] = None, new_clip_at_start: bool = False,
                 clip_seconds: float = 0.0, still_credits: int = 0) -> None:
        self.video, self.made_by, self.clips, self.inputs = video, made_by, clips, inputs
        self.new_clip, self.new_clip_at_start = new_clip, new_clip_at_start
        self.clip_seconds, self.still_credits = clip_seconds, still_credits


class _Context:
    """Services and identities of one change."""

    def __init__(self, task: Any, request: GenerateRequest, arguments: dict[str, Any], target: Any, kept: KeptVideo,
                 *, s3_service: Any, bucket: str, vault_key_id: str,
                 progress: Optional[VideoProgressPublisher] = None) -> None:
        self.progress = progress
        self.task, self.request, self.arguments, self.target, self.kept = task, request, arguments, target, kept
        self.s3_service, self.bucket, self.vault_key_id = s3_service, bucket, vault_key_id
        self.user_id = str(arguments["user_id"])
        self.chat_id = str(arguments["chat_id"])
        self.message_id = str(arguments["message_id"])
        self.log_prefix = f"[videos.generate change task:{task.request.id}]"

    async def read(self, stored: Any) -> bytes:
        from backend.apps.videos.tasks.video_storage import read_stored_object

        data = await read_stored_object(self.task, s3_service=self.s3_service, bucket_name=self.bucket,
                                        stored=stored, vault_key_id=self.vault_key_id)
        if data is None:
            raise ChangeFailed(ERROR_CHANGE_UNAVAILABLE, NOT_KEPT_MESSAGE)
        return data

    async def audio_stage(self, kinds: Any) -> None:
        """Publish the audio stage with the kinds about to be generated."""
        if self.progress is not None:
            await self.progress.on_audio(kinds)

    async def stage(self, stage: str) -> None:
        """Publish one processing update on the card of this change call (never stored)."""
        if self.progress is not None:
            await self.progress(stage)


async def run_change_request(task: Any, request: GenerateRequest, *, source_video_embed_id: str,
                             arguments: dict[str, Any],
                             progress: Optional[VideoProgressPublisher] = None) -> dict[str, Any]:
    """Make version N+1 of ``source_video_embed_id`` as the request says, or fail without a charge."""
    from backend.shared.python_utils.media_revision import VIDEO_KIND, find_revision_target, revisions_enabled

    chat_id, message_id = arguments.get("chat_id"), arguments.get("message_id")
    if not revisions_enabled() or not chat_id or not message_id or arguments.get("external_request"):
        raise ChangeFailed(ERROR_CHANGE_NOT_AVAILABLE, CHANGE_NOT_AVAILABLE_MESSAGE)
    user_id = str(arguments.get("user_id") or "")
    vault_key_id = str(arguments.get("user_vault_key_id") or "")
    if not user_id or not vault_key_id:
        raise ValueError("A video change needs the user and the vault key identifier")
    target = await find_revision_target(
        task._directus_service, reference_embed_ids=[source_video_embed_id], chat_id=str(chat_id), user_id=user_id,
        external_request=False, kind=VIDEO_KIND,
    )
    if target is None:
        raise ChangeFailed(ERROR_INVALID_INPUT, NOT_CHANGEABLE_MESSAGE)
    if progress is not None:
        await progress(STAGE_DECIDING, 1)  # first update before any storage read or model call
    context = await _open(task, request, arguments, target, user_id=user_id, vault_key_id=vault_key_id,
                          progress=progress)
    made = await _make(context)
    return await _deliver(context, made)


async def _open(task: Any, request: GenerateRequest, arguments: dict[str, Any], target: Any, *, user_id: str,
                vault_key_id: str, progress: Optional[VideoProgressPublisher] = None) -> _Context:
    from backend.apps.videos.tasks.video_kept import recall_video
    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

    s3_service = await initialize_task_storage(task)
    await require_storage_available(s3_service)
    bucket = get_bucket_name("chatfiles", s3_service.environment)
    try:
        kept = await recall_video(task, s3_service=s3_service, bucket_name=bucket, user_id=user_id,
                                  embed_id=target.embed_id, version=target.current_version, vault_key_id=vault_key_id)
    except KeptVideoError as exc:
        raise ChangeFailed(ERROR_CHANGE_UNAVAILABLE, NOT_KEPT_MESSAGE) from exc
    if kept is None:
        raise ChangeFailed(ERROR_CHANGE_UNAVAILABLE, NOT_KEPT_MESSAGE)
    return _Context(task, request, arguments, target, kept, s3_service=s3_service, bucket=bucket,
                    vault_key_id=vault_key_id, progress=progress)


async def _make(context: _Context) -> _Made:
    change, kept = context.request.change, context.kept
    if change in (CHANGE_EXTEND_END, CHANGE_EXTEND_START):
        if kept.clips is None:
            raise ChangeFailed(ERROR_INVALID_INPUT, EXTEND_COMPOSED_MESSAGE)
        seconds = context.request.duration_seconds or GENERATIVE_DEFAULT_SECONDS
        if not 3 <= seconds <= EXTEND_MAX_SECONDS:
            raise ChangeFailed(ERROR_INVALID_INPUT, f"An added clip lasts 3 to {EXTEND_MAX_SECONDS} seconds.")
        if visible_seconds(kept.clips) + seconds > MAX_JOINED_SECONDS:
            raise ChangeFailed(ERROR_INVALID_INPUT, f"An extended video lasts at most {MAX_JOINED_SECONDS} seconds. "
                                                    "Nothing was made or charged.")
        _check_prompt(context.request.instructions,
                      named_person_reviewed=context.arguments.get("named_person_reviewed") is True)
        await _ensure_headroom(context, extend_seconds=seconds, still=change == CHANGE_EXTEND_START)
        return await _extend(context, seconds=seconds, at_start=change == CHANGE_EXTEND_START)
    if change != CHANGE_EDIT:
        raise ChangeFailed(ERROR_INVALID_INPUT, "Say whether to edit the video or extend it at its start or end.")
    if kept.clips is not None:
        try:
            trimmed = apply_clip_edits(context.request.instructions, kept.clips)
        except ClipEditError as exc:
            raise ChangeFailed(ERROR_INVALID_INPUT, f"These edits cannot be applied: {exc}. Nothing was charged.") \
                from exc
        if trimmed is not None:
            await _ensure_headroom(context, extend_seconds=0, still=False)
            video = await _join(context, trimmed, {})
            return _Made(video=video, made_by=kept.made_by, clips=trimmed, inputs=())
    await _ensure_headroom(context, extend_seconds=0, still=False, author=True)
    return await _author_edit(context)


def _check_prompt(prompt: str, *, named_person_reviewed: bool) -> None:
    from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

    if not validate_media_generation_request(media_type="video", prompt=prompt, request_count=1,
                                             named_person_reviewed=named_person_reviewed).allowed:
        raise ChangeFailed(ERROR_SAFETY, SAFETY_MESSAGE)


async def _ensure_headroom(context: _Context, *, extend_seconds: int, still: bool, author: bool = False) -> None:
    from backend.apps.videos.composed.author import COMPOSE_AUTHOR_MODELS
    from backend.apps.videos.tasks.generate_billing import estimate_composed_credits, omni_clip_credits

    estimate = await estimate_composed_credits(picture_count=len(context.kept.inputs) if author else 0,
                                               author_model=COMPOSE_AUTHOR_MODELS[0])
    if extend_seconds:
        estimate += omni_clip_credits(context.kept.resolution, extend_seconds)
    estimate += OPENING_STILL_CREDITS if still else 0
    await _ensure_estimate(context, estimate)


async def _ensure_estimate(context: _Context, estimate: int) -> None:
    from backend.shared.python_utils.billing_utils import BillingError, ensure_credit_headroom

    team_id = context.arguments.get("team_id")
    try:
        if team_id:
            from backend.shared.python_utils.team_skill_billing import ensure_team_skill_credit_headroom

            await ensure_team_skill_credit_headroom(context.task._directus_service, team_id, context.user_id, estimate)
        else:
            await ensure_credit_headroom(user_id=context.user_id, estimated_credits=estimate,
                                         log_prefix=context.log_prefix, operation_name="video change")
    except BillingError as exc:
        raise ChangeFailed(ERROR_CREDITS, CREDITS_MESSAGE) from exc
    except ValueError as exc:
        if str(exc) != "INSUFFICIENT_TEAM_CREDITS":
            raise
        raise ChangeFailed(ERROR_CREDITS, CREDITS_MESSAGE) from exc


def _clip_input(context: _Context, index: int, content: bytes) -> Any:
    from backend.apps.videos.composed.models import ComposedInput

    return ComposedInput(name=f"clip-{index}.mp4", content=content, mime_type="video/mp4", width=context.kept.width,
                         height=context.kept.height, title=f"Clip {index}", kind="video_clip")


async def _join(context: _Context, clips: tuple[KeptClip, ...], new: dict[int, bytes]) -> Any:
    """Render the clips in order as one video; ``new`` holds bytes of clips that are not stored yet."""
    from backend.apps.videos.composed.models import ComposedInputError, ComposeFailure
    from backend.apps.videos.composed.source import build_clip_join_source, render_source_directly

    inputs = [_clip_input(context, index, new[index] if index in new else await context.read(clip.stored))
              for index, clip in enumerate(clips, start=1)]
    try:
        source = build_clip_join_source([
            {"name": item.name, "duration_in_frames": clip.duration_in_frames,
             "trim_before_frames": clip.trim_before_frames, "trim_after_frames": clip.trim_after_frames,
             "label": clip.label} for item, clip in zip(inputs, clips)], aspect_ratio=context.kept.aspect_ratio)
        await context.stage(STAGE_RENDERING)
        return await render_source_directly(source, inputs, secrets_manager=context.task._secrets_manager,
                                            task_id=str(context.task.request.id))
    except ComposedInputError as exc:
        raise ChangeFailed(ERROR_INVALID_INPUT, f"This change cannot be made: {exc}. Nothing was charged.") from exc
    except ComposeFailure as exc:
        logger.warning("%s Clip join failed (%s): %s", context.log_prefix, exc.code, exc.message)
        raise ChangeFailed(exc.code, "The changed video could not be rendered, so nothing was charged.") from exc


async def _omni_clip(context: _Context, prompt: str, *, seconds: int, first: bytes, last: Optional[bytes]) -> Any:
    from backend.shared.providers.google.omni_video import (
        OmniInvalidArgumentError,
        OmniSafetyError,
        OmniVideoError,
        generate_omni_video,
    )

    await context.stage(STAGE_GENERATING)
    try:
        return await generate_omni_video(
            prompt, duration_seconds=seconds, aspect_ratio=context.kept.aspect_ratio,
            resolution=context.kept.resolution, first_frame=first, last_frame=last,
            secrets_manager=context.task._secrets_manager,
        )
    except OmniSafetyError as exc:
        raise ChangeFailed(ERROR_SAFETY, SAFETY_MESSAGE) from exc
    except OmniInvalidArgumentError as exc:
        raise ChangeFailed(ERROR_INVALID_INPUT, f"The added clip could not be made: {exc}. Nothing was charged.") \
            from exc
    except OmniVideoError as exc:
        logger.warning("%s Gemini Omni failed: %s", context.log_prefix, exc)
        raise ChangeFailed(ERROR_PROVIDER, PROVIDER_MESSAGE) from exc


async def _opening_still(context: _Context, first: bytes) -> bytes:
    from backend.shared.providers.google.gemini_image import generate_image_google

    # The image wrapper raises plain exceptions for refusals and outages; they propagate, so the batch
    # records the request as failed. Nothing is charged then: the charge comes after storing.
    return await generate_image_google(
        f"{STILL_LINE}{context.request.instructions}", context.task._secrets_manager,
        aspect_ratio=context.kept.aspect_ratio, model_id=OPENING_STILL_MODEL,
        reference_image_bytes_list=[first], reference_image_mime_types=["image/jpeg"],
    )


async def _extend(context: _Context, *, seconds: int, at_start: bool) -> _Made:
    from backend.shared.python_utils.video_frames import extract_frame

    kept = context.kept
    await context.stage(STAGE_GENERATING)
    current = await context.read(kept.video)
    still_credits = 0
    if at_start:
        first = await extract_frame(current, position="first")
        still = await _opening_still(context, first)
        still_credits = OPENING_STILL_CREDITS
        clip = await _omni_clip(context, f"{context.request.instructions}\n{LEAD_IN_LINE}", seconds=seconds,
                                first=still, last=first)
    else:
        last = await extract_frame(current, position="last")
        clip = await _omni_clip(context, f"{context.request.instructions}\n{CONTINUE_LINE}", seconds=seconds,
                                first=last, last=None)
    placeholder = KeptClip(stored=kept.video, duration_in_frames=clip_frames(clip.duration_seconds),
                           trim_before_frames=0, trim_after_frames=0, label=context.request.instructions[:120],
                           model=clip.model)
    clips = (placeholder, *kept.clips) if at_start else (*kept.clips, placeholder)
    new_index = 1 if at_start else len(clips)
    video = await _join(context, clips, {new_index: clip.mp4})
    return _Made(video=video, made_by=kept.made_by, clips=clips, inputs=(), new_clip=clip.mp4,
                 new_clip_at_start=at_start, clip_seconds=clip.duration_seconds, still_credits=still_credits)


async def _author_edit(context: _Context) -> _Made:
    from backend.apps.videos.composed.author import compose_video
    from backend.apps.videos.composed.models import ComposedInput, ComposedInputError, ComposedRequest, ComposeFailure
    from backend.apps.videos.composed.source import build_clip_join_source

    from backend.apps.videos.tasks.generate_billing import composed_credits
    from backend.apps.videos.tasks.video_audio import recall_audio

    async def afford(estimate: int, usage: Any, sandbox_seconds: Any) -> None:
        running, _ = await composed_credits(usage=usage, sandbox_seconds=sandbox_seconds)
        await _ensure_estimate(context, running + estimate)

    kept = context.kept
    if kept.clips is not None:
        inputs = tuple(KeptInput(stored=clip.stored, name=f"clip-{index}.mp4", mime_type="video/mp4",
                                 width=kept.width, height=kept.height, title=f"Clip {index}", kind="video_clip",
                                 embed_id=context.target.embed_id, ref=context.target.embed_ref)
                       for index, clip in enumerate(kept.clips, start=1))
        source = build_clip_join_source([
            {"name": item.name, "duration_in_frames": clip.duration_in_frames,
             "trim_before_frames": clip.trim_before_frames, "trim_after_frames": clip.trim_after_frames,
             "label": clip.label} for item, clip in zip(inputs, kept.clips)], aspect_ratio=kept.aspect_ratio)
    else:
        inputs, source = kept.inputs, kept.source
    if not source:
        raise ChangeFailed(ERROR_CHANGE_UNAVAILABLE, NOT_KEPT_MESSAGE)
    composed_inputs = tuple([ComposedInput(name=item.name, content=await context.read(item.stored),
                                           mime_type=item.mime_type, width=item.width, height=item.height,
                                           title=item.title, kind=item.kind) for item in inputs])
    try:
        video = await compose_video(
            ComposedRequest(instructions=context.request.instructions, aspect_ratio=kept.aspect_ratio,
                            duration_seconds=context.request.duration_seconds, inputs=composed_inputs,
                            previous_source=source, previous_audio=await recall_audio(kept.audio, context.read)),
            secrets_manager=context.task._secrets_manager, task_id=str(context.task.request.id),
            on_stage=context.stage, on_audio=context.audio_stage, afford_audio=afford,
        )
    except ComposedInputError as exc:
        raise ChangeFailed(ERROR_INVALID_INPUT, f"The video could not be changed: {exc}. Nothing was charged.") \
            from exc
    except ComposeFailure as exc:
        logger.warning("%s Authored change failed (%s): %s", context.log_prefix, exc.code, exc.message)
        if exc.code == "audio_rejected":
            raise ChangeFailed(ERROR_SAFETY, f"{exc.message} Nothing was charged.") from exc
        if exc.code == "audio_failed":
            raise ChangeFailed(exc.code, "The sound for the changed video could not be made, so nothing was "
                                         "charged.") from exc
        raise ChangeFailed(exc.code, "The changed video could not be made, so nothing was charged.") from exc
    return _Made(video=video, made_by=kept.made_by, clips=None, inputs=inputs)


async def _deliver(context: _Context, made: _Made) -> dict[str, Any]:
    from backend.apps.videos.tasks.change_delivery import deliver_change

    return await deliver_change(context, made)
