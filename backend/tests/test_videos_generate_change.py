# backend/tests/test_videos_generate_change.py
#
# Changing an earlier videos.generate result becomes the next version of the same
# embed (videos-generate.change.*, .billing.metered). No network: every model,
# the sandbox, storage reads, billing and publication are stubbed; the encryption
# of uploaded files and the kept record use the real helpers.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.videos.composed import author as author_module
from backend.apps.videos.composed.audio_clips import GeneratedClip
from backend.apps.videos.composed.audio_step import UsedClip
from backend.apps.videos.composed import source as source_module
from backend.apps.videos.composed.models import ComposedVideo
from backend.apps.videos.generate_request import parse_generate_request
from backend.apps.videos.tasks import change_edits, generate_billing, generate_change, generate_pipeline
from backend.apps.videos.tasks import video_kept, video_storage
from backend.apps.videos.tasks.video_kept import KeptAudio, KeptClip, KeptInput, KeptVideo
from backend.apps.videos.tasks.video_storage import StoredObject
from backend.shared.providers.google import gemini_image, omni_video
from backend.shared.python_utils import billing_utils, media_revision, storage_availability, video_frames

EMBED_ID = "5f0c1d7e-1111-5aaa-8bbb-222233334444"
CHANGE_ID = "c" * 32
CONTINUE = generate_change.CONTINUE_LINE


def _stored(key: str, size: int = 10) -> StoredObject:
    return StoredObject(s3_key=key, variant={"encryption": "aes-gcm-nonce-prefixed-v1"},
                        vault_wrapped_aes_key="vault:v1:wrapped", size_bytes=size)


def _generative(frames: int = 240) -> KeptVideo:
    video = _stored("user-1/v1_original.mp4")
    return KeptVideo(version=1, made_by="generative", aspect_ratio="16:9", resolution="720p", width=1280,
                     height=720, video=video,
                     clips=(KeptClip(stored=video, duration_in_frames=frames, trim_before_frames=0,
                                     trim_after_frames=0, label="Sunrise", model="gemini-omni-1.2-flash"),))


def _composed() -> KeptVideo:
    return KeptVideo(version=1, made_by="composed", aspect_ratio="16:9", resolution="", width=1920, height=1080,
                     video=_stored("user-1/v1_original.mp4"), source="export default Main; // kept",
                     inputs=(KeptInput(stored=_stored("user-1/v1_input-1.jpg"), name="input-1.jpg",
                                       mime_type="image/jpeg", width=800, height=600, title="Harbour", kind="image",
                                       embed_id="pic-1", ref="harbour-photo"),))


def _rendered(frames: int, *, author: str = "") -> ComposedVideo:
    return ComposedVideo(mp4=b"rendered-mp4", thumbnail_png=b"png", source="joined", filename="Composition.tsx",
                         timeline={"fps": 30, "width": 1280, "height": 720, "duration_in_frames": frames, "parts": []},
                         fps=30, width=1280, height=720, duration_in_frames=frames, attempts=1, author_model=author,
                         usage=(), sandbox_seconds=(20.0,))


def _clip(seconds: float) -> omni_video.OmniVideo:
    return omni_video.OmniVideo(mp4=b"new-clip-mp4", duration_seconds=seconds, width=1280, height=720,
                                model="gemini-omni-1.2-flash", input_tokens=0, output_tokens=0, thought_tokens=0)


class _S3:
    base_domain = "s3.example.test"
    environment = "development"

    def __init__(self):
        self.uploads, self.deleted = [], []

    async def upload_file(self, bucket, key, content, content_type):
        self.uploads.append((bucket, key, content))

    async def delete_file(self, bucket, key):
        self.deleted.append((bucket, key))


class _Encryption:
    async def encrypt_with_user_key(self, value, vault_key_id):
        return f"vault:v1:{len(value)}", None


def _task():
    return SimpleNamespace(request=SimpleNamespace(id="task-change-1"), _directus_service=object(),
                           _cache_service=object(), _encryption_service=_Encryption(), _secrets_manager=object())


@pytest.fixture
def world(monkeypatch):
    """A generated video of this chat at version 1, with every outside service stubbed."""
    monkeypatch.setenv(media_revision.REVISIONS_ENV, "true")
    target = media_revision.RevisionTarget(
        embed_id=EMBED_ID, parent_embed_id="parent-1", current_version=1,
        s3_file_keys=({"bucket": "chatfiles", "key": "user-1/v1_original.mp4"},), upload_record_id="upload-1",
        base_snapshot_required=False, hashed_message_id="a" * 64, retained_size_bytes=100, change_id=CHANGE_ID,
        kind=media_revision.VIDEO_KIND,
    )
    s3 = _S3()
    state = SimpleNamespace(target=target, s3=s3, kept=_generative(), published=[], finished=[])
    monkeypatch.setattr(media_revision, "find_revision_target", AsyncMock(return_value=target))
    monkeypatch.setattr(media_revision, "assert_current_version", AsyncMock())
    monkeypatch.setattr(media_revision, "cache_file_keys",
                        AsyncMock(side_effect=lambda task, *, target, new_keys: media_revision.union_file_keys(
                            target.s3_file_keys, new_keys)))

    async def publish(embed_service, **kwargs):
        state.published.append(kwargs)
        return kwargs["target"].embed_ref

    async def finish(task, *, target, index, log_prefix):
        state.finished.append(await index())

    monkeypatch.setattr(media_revision, "publish_revision", publish)
    monkeypatch.setattr(media_revision, "finish_published_revision", finish)
    monkeypatch.setattr(media_revision, "refund_refused_revision", AsyncMock())
    monkeypatch.setattr(storage_availability, "initialize_task_storage", AsyncMock(return_value=s3))
    monkeypatch.setattr(storage_availability, "require_storage_available", AsyncMock())
    monkeypatch.setattr(video_kept, "recall_video", AsyncMock(side_effect=lambda *a, **k: state.kept))
    monkeypatch.setattr(video_storage, "read_stored_object",
                        AsyncMock(side_effect=lambda task, *, stored, **k: f"bytes:{stored.s3_key}".encode()))
    monkeypatch.setattr(video_storage, "index_video", AsyncMock(return_value=True))
    monkeypatch.setattr(video_frames, "extract_frame",
                        AsyncMock(side_effect=lambda mp4, *, position: f"{position}-frame".encode()))
    monkeypatch.setattr(generate_pipeline, "check_output_frames", AsyncMock())
    monkeypatch.setattr(generate_pipeline, "_embed_service", lambda task: object())
    state.charge = AsyncMock(return_value="charged")
    monkeypatch.setattr(generate_pipeline, "_charge", state.charge)
    monkeypatch.setattr(generate_billing, "composed_credits", AsyncMock(return_value=(5, {"sandbox_minutes": 1})))
    monkeypatch.setattr(generate_billing, "estimate_composed_credits", AsyncMock(return_value=50))
    monkeypatch.setattr(billing_utils, "ensure_credit_headroom", AsyncMock())
    state.render = AsyncMock(side_effect=lambda source, inputs, **k: _rendered(
        sum(1 for _ in inputs) * 0 + 300))
    monkeypatch.setattr(source_module, "render_source_directly", state.render)
    state.compose = AsyncMock(return_value=_rendered(240, author="anthropic/claude-haiku-5-5"))
    monkeypatch.setattr(author_module, "compose_video", state.compose)
    state.omni = AsyncMock(return_value=_clip(4.0))
    monkeypatch.setattr(omni_video, "generate_omni_video", state.omni)
    state.still = AsyncMock(return_value=b"opening-still")
    monkeypatch.setattr(gemini_image, "generate_image_google", state.still)
    return state


def _request(change: str, instructions: str, duration=None):
    return parse_generate_request({"instructions": instructions, "source_video": "generated-videos-5f0c1d7e1111",
                                   "change": change, "duration_seconds": duration})


def _arguments():
    return {"user_id": "user-1", "user_vault_key_id": "vault-1", "chat_id": "chat-1", "message_id": "message-2"}


async def _run(world, change, instructions, duration=None):
    return await generate_change.run_change_request(_task(), _request(change, instructions, duration),
                                                    source_video_embed_id=EMBED_ID, arguments=_arguments())


def _join_clips(world):
    source, inputs = world.render.await_args.args
    return source, [item.name for item in inputs], [item.content for item in inputs]


# contract-test: supporting surface=gui.web assertions=videos-generate.change.extend-generated-clip,videos-generate.change.same-video-next-version,videos-generate.billing.metered
@pytest.mark.asyncio
async def test_extend_end_continues_from_the_last_frame_and_publishes_version_two(world):
    result = await _run(world, "extend_end", "The sun rises over the hills", duration=4)

    omni = world.omni.await_args
    assert omni.kwargs["first_frame"] == b"last-frame" and omni.kwargs["last_frame"] is None
    assert (omni.kwargs["duration_seconds"], omni.kwargs["aspect_ratio"], omni.kwargs["resolution"]) == (4, "16:9", "720p")
    assert omni.args[0] == f"The sun rises over the hills\n{CONTINUE}"
    source, names, contents = _join_clips(world)
    assert names == ["clip-1.mp4", "clip-2.mp4"]
    assert contents == [b"bytes:user-1/v1_original.mp4", b"new-clip-mp4"]
    assert '"durationInFrames": 240' in source and '"durationInFrames": 120' in source
    # One charge for what the change used: 4 s at 720p (420) plus the render (5), under the version key.
    charge = world.charge.await_args.kwargs
    assert charge["credits"] == 425
    assert charge["event_id"] == f"{EMBED_ID}:v2:{CHANGE_ID}"
    assert charge["usage_details"]["added_clip_seconds"] == 4.0
    published = world.published[0]
    assert published["target"].next_version == 2
    content = published["content"]
    assert (content["version"], content["made_by"], content["change"]) == (2, "generative", "extend_end")
    assert content["revised_from"] == {"embed_id": EMBED_ID, "version": 1}
    assert content["can_extend_end"] is True
    # Every version's files stay in the embed's file index (union), including the new clip and kept record.
    keys = [ref["key"] for ref in published["s3_file_keys"]]
    assert keys[0] == "user-1/v1_original.mp4"
    assert any(key.endswith("_clip-new.mp4") for key in keys)
    assert f"user-1/videos_kept/{EMBED_ID}/v2.json" in keys
    assert result["embed_id"] == EMBED_ID and result["revision"] is True
    assert result["pinned_embed"] == {"embed_id": EMBED_ID, "version": 2, "embed_ref": "generated-videos-5f0c1d7e1111",
                                      "previous_version": 1}
    assert world.finished == [True]
    index = video_storage.index_video.await_args.kwargs
    assert (index["existing_record_id"], index["retained_size_bytes"]) == ("upload-1", 100)


# contract-test: supporting surface=gui.web assertions=videos-generate.change.extend-generated-clip
@pytest.mark.asyncio
async def test_extend_end_kept_record_lists_both_clips(world, monkeypatch):
    remember = AsyncMock(return_value=f"user-1/videos_kept/{EMBED_ID}/v2.json")
    monkeypatch.setattr(video_kept, "remember_video", remember)
    await _run(world, "extend_end", "The sun rises", duration=4)
    kept = remember.await_args.kwargs["kept"]
    assert kept.version == 2 and kept.made_by == "generative"
    assert [clip.duration_in_frames for clip in kept.clips] == [240, 120]
    assert kept.clips[0].stored.s3_key == "user-1/v1_original.mp4"
    assert kept.clips[1].stored.s3_key.endswith("_clip-new.mp4")


# contract-test: supporting surface=gui.web assertions=videos-generate.change.extend-generated-clip,videos-generate.billing.metered
@pytest.mark.asyncio
async def test_extend_start_makes_an_opening_still_and_a_lead_in_clip_first(world):
    await _run(world, "extend_start", "A quiet night before the sunrise", duration=3)

    still = world.still.await_args
    assert still.kwargs["model_id"] == "gemini-nano-banana-2.1"
    assert still.kwargs["reference_image_bytes_list"] == [b"first-frame"]
    omni = world.omni.await_args.kwargs
    assert (omni["first_frame"], omni["last_frame"], omni["duration_seconds"]) == (b"opening-still", b"first-frame", 3)
    _source, names, contents = _join_clips(world)
    assert contents == [b"new-clip-mp4", b"bytes:user-1/v1_original.mp4"]
    assert names == ["clip-1.mp4", "clip-2.mp4"]
    assert world.charge.await_args.kwargs["credits"] == 420 + 5 + 63


# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode
@pytest.mark.asyncio
async def test_structured_trim_of_a_clip_is_rendered_without_the_author(world):
    instructions = ("Apply these edits to this video:\n"
                    "- Trim the video: remove 0.5 s from the start and 1.0 s from the end")
    await _run(world, "edit", instructions)

    world.compose.assert_not_awaited()
    world.omni.assert_not_awaited()
    source, names, _contents = _join_clips(world)
    assert names == ["clip-1.mp4"]
    assert '"trimBefore": 15' in source and '"trimAfter": 210' in source
    assert world.charge.await_args.kwargs["credits"] == 5
    assert world.published[0]["content"]["can_extend_end"] is True


# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode
@pytest.mark.asyncio
async def test_free_edit_of_a_clip_goes_to_the_author_with_the_join_source(world):
    await _run(world, "edit", "Make the colours warmer and add a title")

    world.render.assert_not_awaited()
    request = world.compose.await_args.args[0]
    assert "OffthreadVideo" in request.previous_source
    assert [(item.name, item.kind, item.content) for item in request.inputs] == [
        ("clip-1.mp4", "video_clip", b"bytes:user-1/v1_original.mp4")]
    content = world.published[0]["content"]
    # Once authored, the clips are no longer a plain join: no extending from here.
    assert content["can_extend_end"] is False


# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode,videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_edit_of_a_composed_video_renders_again_from_the_original_pictures(world):
    world.kept = _composed()
    await _run(world, "edit", "Change the headline to Harbour festival")

    request = world.compose.await_args.args[0]
    assert request.previous_source == "export default Main; // kept"
    assert [(item.name, item.content, item.title) for item in request.inputs] == [
        ("input-1.jpg", b"bytes:user-1/v1_input-1.jpg", "Harbour")]
    content = world.published[0]["content"]
    assert (content["version"], content["made_by"], content["can_extend_end"]) == (2, "composed", False)


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_lost_version_race_is_not_charged_and_uploads_nothing(world):
    media_revision.assert_current_version.side_effect = media_revision.RevisionPreconditionFailed("moved")
    with pytest.raises(generate_change.ChangeFailed) as failure:
        await _run(world, "edit", "- Trim the video: remove 1.0 s from the end")
    assert failure.value.code == generate_change.ERROR_VERSION_CHANGED
    world.charge.assert_not_awaited()
    assert world.s3.uploads == [] and world.published == []


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_failed_change_keeps_the_current_version(world):
    world.omni.side_effect = omni_video.OmniSafetyError("blocked")
    with pytest.raises(generate_change.ChangeFailed) as failure:
        await _run(world, "extend_end", "Something", duration=4)
    assert failure.value.code == generate_change.ERROR_SAFETY
    world.charge.assert_not_awaited()
    assert world.published == [] and world.s3.uploads == []


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_refused_version_is_refunded(world, monkeypatch):
    from backend.core.api.app.services.embed_revision_authority import RevisionRefused

    async def refuse(embed_service, **kwargs):
        raise RevisionRefused("stale")

    monkeypatch.setattr(media_revision, "publish_revision", refuse)
    with pytest.raises(RevisionRefused):
        await _run(world, "extend_end", "More sunrise", duration=4)
    refund = media_revision.refund_refused_revision.await_args.kwargs
    assert (refund["credits"], refund["event_id"], refund["noun"]) == (425, f"{EMBED_ID}:v2:{CHANGE_ID}", "video")


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_switch_off_refuses_before_reading_anything(world, monkeypatch):
    monkeypatch.delenv(media_revision.REVISIONS_ENV)
    with pytest.raises(generate_change.ChangeFailed) as failure:
        await _run(world, "extend_end", "More", duration=4)
    assert failure.value.code == generate_change.ERROR_CHANGE_NOT_AVAILABLE
    media_revision.find_revision_target.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_video_without_kept_record_fails_before_any_paid_call(world):
    world.kept = None
    with pytest.raises(generate_change.ChangeFailed) as failure:
        await _run(world, "extend_end", "More", duration=4)
    assert failure.value.code == generate_change.ERROR_CHANGE_UNAVAILABLE
    world.omni.assert_not_awaited()
    world.charge.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=videos-generate.change.extend-generated-clip
@pytest.mark.asyncio
async def test_composed_video_cannot_be_extended(world):
    world.kept = _composed()
    with pytest.raises(generate_change.ChangeFailed, match="Only a video made of generated clips"):
        await _run(world, "extend_start", "More", duration=4)
    world.still.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=videos-generate.change.extend-generated-clip
@pytest.mark.asyncio
async def test_extend_beyond_sixty_seconds_is_refused_before_generation(world):
    world.kept = _generative(frames=55 * 30)
    with pytest.raises(generate_change.ChangeFailed, match="at most 60 seconds"):
        await _run(world, "extend_end", "More", duration=8)
    world.omni.assert_not_awaited()


def _clips(*frames):
    return tuple(KeptClip(stored=_stored(f"clip-{index}"), duration_in_frames=count, trim_before_frames=0,
                          trim_after_frames=0, label=f"Part {index}") for index, count in enumerate(frames, start=1))


# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode
def test_structured_edit_lines_apply_per_part_and_across_parts():
    clips = _clips(120, 90, 150)
    text = ("Apply these edits to this video:\n"
            '- Part "Part 1" (id clip-1): shorten by 1.0 s at the end\n'
            '- Remove part "Part 2" (id clip-2)\n'
            "- Trim the video: remove 5.0 s from the end")
    result = change_edits.apply_clip_edits(text, clips)
    # clip-1 keeps 90 frames; clip-3 (150) loses 150 of the 150-frame end trim and is dropped,
    # so the end trim stops exactly at clip-1's end.
    assert [(clip.label, clip.trim_before_frames, clip.trim_after_frames) for clip in result] == [("Part 1", 0, 30)]


# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode
def test_whole_video_trim_spills_into_the_next_clip():
    result = change_edits.apply_clip_edits("- Trim the video: remove 5.0 s from the start", _clips(120, 120))
    assert [(clip.label, clip.trim_before_frames) for clip in result] == [("Part 2", 30)]


@pytest.mark.parametrize("text", [
    "Make it warmer",
    '- Part "Budget vote" (id scene-2): change text "headline" from "Old" to "New"',
    '- Part "Part 1" (id clip-9): shorten by 1.0 s at the end',
    "- Kürze das Video am Ende um 1,0 s",
])
# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode
def test_anything_but_structured_clip_trims_goes_to_the_author(text):
    assert change_edits.apply_clip_edits(text, _clips(120)) is None


# contract-test: supporting surface=gui.web assertions=videos-generate.change.edit-mode
def test_trimming_away_the_whole_video_is_an_error():
    with pytest.raises(change_edits.ClipEditError):
        change_edits.apply_clip_edits("- Trim the video: remove 4.0 s from the start and 1.0 s from the end", _clips(120))


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_publish_transport_failure_refunds_and_deletes_uploads(world, monkeypatch):
    async def broken(embed_service, **kwargs):
        raise ConnectionError("publish transport")

    monkeypatch.setattr(media_revision, "publish_revision", broken)
    with pytest.raises(ConnectionError):
        await _run(world, "extend_end", "More sunrise", duration=4)
    assert media_revision.refund_refused_revision.await_args.kwargs["credits"] == 425
    assert world.s3.uploads and {(b, k) for b, k, _ in world.s3.uploads} <= set(world.s3.deleted)


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_version_check_runs_before_the_frame_safety_check(world):
    media_revision.assert_current_version.side_effect = media_revision.RevisionPreconditionFailed("moved")
    with pytest.raises(generate_change.ChangeFailed):
        await _run(world, "edit", "- Trim the video: remove 1.0 s from the end")
    generate_pipeline.check_output_frames.assert_not_awaited()


def world_calls(world):
    """How often a clip model, the author, the sandbox render and the still model were used so far."""
    return (world.omni.await_count, world.compose.await_count, world.render.await_count, world.still.await_count)


async def _run_with_progress(world, change, instructions, duration=None):
    from backend.apps.videos.tasks.generate_progress import VideoProgressPublisher

    sent = []

    class Service:
        async def send_embed_data_to_client(self, **kwargs):
            from toon_format import decode as toon_decode

            sent.append((world_calls(world), kwargs, toon_decode(kwargs["content_toon"])))

    progress = VideoProgressPublisher(Service(), skill_id="generate", embed_id="child-1", parent_embed_id="parent-1",
                                      user_id="user-1", chat_id="chat-1", message_id="message-2",
                                      instructions=instructions, input_embed_ids=[], log_prefix="[test]")
    progress.mark_change(change, EMBED_ID)
    await generate_change.run_change_request(_task(), _request(change, instructions, duration),
                                             source_video_embed_id=EMBED_ID, arguments=_arguments(), progress=progress)
    return sent


# contract-test: supporting surface=rest_api assertions=videos-generate.progress.shown-while-running
@pytest.mark.asyncio
async def test_change_publishes_its_first_update_before_any_model_call(world):
    sent = await _run_with_progress(world, "extend_end", "The sun rises over the hills", duration=4)
    calls, kwargs, first = sent[0]
    assert calls == (0, 0, 0, 0)
    assert (first["change"], first["source_embed_id"], first["prompt"]) == (
        "extend_end", EMBED_ID, "The sun rises over the hills")
    assert (first["status"], first["progress_stage"], first["progress_attempt"]) == ("processing", "deciding", 1)
    assert (kwargs["embed_id"], kwargs["parent_embed_id"], kwargs["status"]) == ("child-1", "parent-1", "processing")
    assert "key" not in " ".join(first) and "http" not in str(first)


# contract-test: supporting surface=rest_api assertions=videos-generate.progress.shown-while-running
@pytest.mark.asyncio
async def test_extend_end_of_a_generative_clip_goes_generating_then_rendering(world):
    sent = await _run_with_progress(world, "extend_end", "More sunrise", duration=4)
    assert [content["progress_stage"] for _calls, _kwargs, content in sent] == ["deciding", "generating", "rendering"]
    assert {content["change"] for _c, _k, content in sent} == {"extend_end"}


# contract-test: supporting surface=rest_api assertions=videos-generate.progress.shown-while-running
@pytest.mark.asyncio
async def test_edit_of_a_composed_video_shows_the_author_stages(world):
    world.kept = _composed()

    async def compose(request, *, on_stage, **_kwargs):
        for stage in ("writing", "rendering", "correcting", "rendering"):
            await on_stage(stage)
        return _rendered(240, author="anthropic/claude-haiku-5-5")

    world.compose.side_effect = compose
    sent = await _run_with_progress(world, "edit", "Change the headline to Harbour festival")
    contents = [content for _calls, _kwargs, content in sent]
    assert [c["progress_stage"] for c in contents] == ["deciding", "writing", "rendering", "correcting", "rendering"]
    assert [c["progress_attempt"] for c in contents] == [1, 1, 1, 2, 2]
    assert {c["change"] for c in contents} == {"edit"} and {c["source_embed_id"] for c in contents} == {EMBED_ID}


# contract-test: supporting surface=rest_api assertions=videos-generate.progress.shown-while-running
def test_non_change_progress_content_is_unchanged():
    from backend.apps.videos.tasks.generate_progress import processing_content

    content = processing_content(skill_id="generate", instructions="A video", input_embed_ids=["a"],
                                 stage="writing", attempt=1)
    assert set(content) == {"app_id", "skill_id", "type", "status", "prompt", "input_embed_ids", "progress_stage",
                            "progress_attempt"}


# contract-test: supporting surface=rest_api assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_edit_offers_the_kept_audio_clips_for_reuse_and_keeps_new_ones(world):
    kept = _composed()
    world.kept = KeptVideo(**{**kept.__dict__, "audio": (
        KeptAudio(stored=_stored("user-1/v1_audio-1.mp3"), hash="h-speech", kind="speech", duration_seconds=3.0,
                  mime_type="audio/mpeg", provider="ElevenLabs", model="eleven_v4"),)})
    made = GeneratedClip("knock", "sound", b"knock-bytes", "audio/mpeg", 2.0, "ElevenLabs", "sound", 2.0)
    reused = UsedClip("h-speech", GeneratedClip("voice-1", "speech", b"bytes:user-1/v1_audio-1.mp3", "audio/mpeg",
                                                3.0, "ElevenLabs", "eleven_v4", 3.0))
    rendered = _rendered(240, author="anthropic/claude-haiku-5-5")
    world.compose.return_value = ComposedVideo(
        **{**rendered.__dict__, "audio": (reused, UsedClip("h-sound", made)), "audio_generated": (made,),
           "timeline": {**rendered.timeline, "audio": [{"id": "knock", "kind": "sound", "label": "door",
                                                          "from": 0, "durationInFrames": 60}]}})
    await _run(world, "edit", "Add a door knock at the start")

    request = world.compose.await_args.args[0]
    [offered] = request.previous_audio
    assert (offered.hash, offered.clip.kind, offered.clip.data, offered.clip.duration_seconds) == (
        "h-speech", "speech", b"bytes:user-1/v1_audio-1.mp3", 3.0)
    assert world.compose.await_args.kwargs["afford_audio"] is not None
    # Only the clip generated in this change is charged; the stored version keeps both clips.
    charged = world.charge.await_args.kwargs
    assert charged["credits"] == 5 + 30 and charged["usage_details"]["audio_credits"]["sound"] == 30
    assert world.published[0]["content"]["has_audio"] is True
    uploaded = [key for _bucket, key, _content in world.s3.uploads]
    assert sum("audio-" in key for key in uploaded) == 2
    record = next(content for _b, key, content in world.s3.uploads if key.endswith("/v2.json"))
    assert record  # the kept record of version 2 was written, encrypted
