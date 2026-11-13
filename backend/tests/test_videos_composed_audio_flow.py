"""Sound in the composed-video rounds: plan, per-request cache, progress, timeline, failures, reuse on change.

Specification: feature.app-skill.videos-generate. Author model, sandbox and audio providers are fakes; no network.
Pipeline charging and the change path are covered next to their other tests (test_videos_generate_pipeline.py,
test_videos_generate_change.py).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.apps.videos.composed.audio_clips import (
    AudioGenerationError,
    AudioRejectedError,
    GeneratedAudio,
    GeneratedClip,
)
from backend.apps.videos.composed.audio_plan import build_audio_plan
from backend.apps.videos.composed.audio_step import AudioStep, UsedClip, clip_hash
from backend.apps.videos.composed.author import compose_video
from backend.apps.videos.composed.contract import InvalidCompositionError, validate_source
from backend.apps.videos.composed.models import ComposeFailure
from backend.apps.videos.tasks.generate_progress import processing_content
from backend.shared.providers.e2b_remotion_renderer import (
    RemotionCheck,
    RemotionCompositionError,
)
from backend.tests.test_videos_composed_author import GOOD, PARTS, VIDEO, FakeSession, _request, _stream

SPEECH = {"id": "voice-1", "kind": "speech", "text": "Spring in Lisbon, three days.", "from": 0}
SOUND = {"id": "knock", "kind": "sound", "prompt": "soft door knock", "durationSeconds": 2, "from": 30}
MUSIC = {"id": "bed", "kind": "music", "prompt": "warm acoustic guitar", "from": 0, "durationInFrames": 120}
PLAN_VIDEO = {"fps": 30, "durationInFrames": 240, "width": 1280, "height": 720}


class AudioSession(FakeSession):
    """FakeSession that reports an ``audio`` export and records the audio uploads."""

    def __init__(self, audio, **kwargs) -> None:
        super().__init__(**kwargs)
        self.audio = audio
        self.audio_uploads: list[tuple[list[str], list[dict]]] = []

    async def check(self, source):
        self.sources.append(source)
        outcome = self.checks.pop(0) if self.checks else RemotionCheck(VIDEO, PARTS, 12.0, audio=self.audio)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def upload_audio(self, assets, tracks):
        self.audio_uploads.append(([asset.name for asset in assets], list(tracks)))


class FakeGenerator:
    """Stands in for ``generate_audio``: records every generated plan and can fail or refuse."""

    def __init__(self, error: Exception | None = None) -> None:
        self.plans: list = []
        self.error = error

    async def __call__(self, plan, *, secrets_manager, **_kwargs):
        self.plans.append(plan)
        if self.error:
            raise self.error
        clips = tuple(GeneratedClip(entry.id, entry.kind, f"{entry.kind}-bytes".encode(), "audio/mpeg",
                                    3.0 if entry.kind != "music" else 4.0, "ElevenLabs", "model",
                                    3.0 if entry.kind != "music" else 1.0) for entry in plan.entries)
        return GeneratedAudio(clips=clips)

    @property
    def generated_ids(self) -> list[str]:
        return [entry.id for plan in self.plans for entry in plan.entries]


def _run(request, stream, session, generator, **kwargs):
    stages: list[str] = []
    kinds: list[tuple[str, ...]] = []

    async def on_stage(stage):
        stages.append(stage)

    async def on_audio(found):
        kinds.append(tuple(found))
        stages.append("audio")

    try:
        result = asyncio.run(compose_video(request, secrets_manager=None, task_id="t1", on_stage=on_stage,
                                           on_audio=on_audio, stream_fn=stream, session_factory=lambda: session,
                                           audio_generate=generator, **kwargs))
    except ComposeFailure as failure:
        return failure, stages, kinds
    return result, stages, kinds


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_audio_is_generated_once_across_a_correction_round():
    session = AudioSession([SPEECH, SOUND], renders=[RemotionCompositionError("render", "boom", 7.0)])
    generator = FakeGenerator()
    video, stages, _kinds = _run(_request(), _stream(GOOD, GOOD), session, generator)
    assert generator.generated_ids == ["voice-1", "knock"]  # one provider pass for two rounds
    assert len(session.audio_uploads) == 2  # the corrected render still gets its audio again
    assert [item.clip.id for item in video.audio] == ["voice-1", "knock"]
    assert [clip.id for clip in video.audio_generated] == ["voice-1", "knock"]
    assert stages.count("audio") == 1 and video.attempts == 2


# contract-test: supporting surface=rest_api assertions=videos-generate.progress.shown-while-running
def test_audio_stage_names_the_kinds_in_order_and_is_skipped_when_everything_is_cached():
    session = AudioSession([MUSIC, SOUND, SPEECH])
    video, stages, kinds = _run(_request(), _stream(GOOD), session, FakeGenerator())
    assert kinds == [("speech", "sound", "music")]
    assert stages == ["writing", "rendering", "audio", "rendering"]
    again = AudioSession([MUSIC, SOUND, SPEECH])
    generator = FakeGenerator()
    request = _request(previous_audio=video.audio)
    cached, stages, kinds = _run(request, _stream(GOOD), again, generator)
    assert generator.plans == [] and kinds == [] and "audio" not in stages
    assert cached.audio_generated == () and len(again.audio_uploads) == 1


# contract-test: supporting surface=rest_api assertions=videos-generate.progress.shown-while-running
def test_progress_content_carries_the_audio_kinds_only_on_the_audio_stage():
    content = processing_content(skill_id="generate", instructions="x", input_embed_ids=[], stage="audio", attempt=1,
                                 audio=("music", "speech"))
    assert content["progress_stage"] == "audio" and content["progress_audio"] == ["speech", "music"]
    assert "progress_audio" not in processing_content(skill_id="generate", instructions="x", input_embed_ids=[],
                                                      stage="rendering", attempt=1)
    with pytest.raises(ValueError):
        processing_content(skill_id="generate", instructions="x", input_embed_ids=[], stage="audio", attempt=1)


# contract-test: supporting surface=rest_api assertions=videos-generate.result.video-with-timeline
def test_timeline_lists_what_really_plays():
    line = "A very long narration line that is cut off at forty chars."
    session = AudioSession([{**SPEECH, "text": line}, MUSIC])
    video, _stages, _kinds = _run(_request(), _stream(GOOD), session, FakeGenerator())
    speech, music = video.timeline["audio"]
    assert speech == {"id": "voice-1", "kind": "speech", "label": line[:40], "from": 0, "durationInFrames": 90,
                      "text": line}
    assert music == {"id": "bed", "kind": "music", "label": "warm acoustic guitar", "from": 0,
                     "durationInFrames": 120}
    assert session.audio_uploads[0][1][0]["durationInFrames"] == 90


# contract-test: supporting surface=rest_api assertions=videos-generate.result.video-with-timeline
def test_a_video_without_audio_has_no_timeline_audio_and_no_upload():
    session = AudioSession(None)
    video, stages, _kinds = _run(_request(), _stream(GOOD), session, FakeGenerator())
    assert "audio" not in video.timeline and video.audio == () and session.audio_uploads == []
    assert "audio" not in stages


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_an_invalid_audio_plan_is_a_failed_round_that_goes_back_to_the_author():
    bad = [{**SPEECH, "voice": "robot"}]
    session = AudioSession([SPEECH])
    session.checks = [RemotionCheck(VIDEO, PARTS, 5.0, audio=bad)]  # the first round reports a bad plan
    stream = _stream(GOOD, GOOD)
    generator = FakeGenerator()
    video, _stages, _kinds = _run(_request(), stream, session, generator)
    assert "voice must be one of" in stream.calls[1]["message_history"][2]["content"]
    assert video.attempts == 2 and generator.generated_ids == ["voice-1"]


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_rejected_narration_ends_the_request_with_the_reason_and_kills_the_sandbox():
    session = AudioSession([SPEECH])
    generator = FakeGenerator(AudioRejectedError("speech", "voice-1", "This narration is not allowed."))
    failure, _stages, _kinds = _run(_request(), _stream(GOOD), session, generator)
    assert isinstance(failure, ComposeFailure) and failure.code == "audio_rejected"
    assert failure.message == "This narration is not allowed." and session.killed
    assert session.audio_uploads == [] and session.frames == []


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_provider_failure_fails_explicitly_without_a_silent_video():
    session = AudioSession([SPEECH])
    generator = FakeGenerator(AudioGenerationError("speech", "voice-1", "provider down"))
    failure, _stages, _kinds = _run(_request(), _stream(GOOD), session, generator)
    assert isinstance(failure, ComposeFailure) and failure.code == "audio_failed"
    assert "voice-1" in failure.message and session.frames == []


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_unaffordable_audio_fails_before_any_provider_call():
    seen = []

    async def afford(estimate, usage, sandbox_seconds):
        seen.append((estimate, len(usage), sandbox_seconds))
        raise RuntimeError("no credits")

    session = AudioSession([SPEECH, MUSIC])
    generator = FakeGenerator()
    with pytest.raises(RuntimeError, match="no credits"):
        asyncio.run(compose_video(_request(), secrets_manager=None, task_id="t1", stream_fn=_stream(GOOD),
                                  session_factory=lambda: session, audio_generate=generator, afford_audio=afford))
    assert generator.plans == [] and session.killed
    estimate, calls, seconds = seen[0]
    assert estimate > 0 and calls == 1 and seconds == ()


# contract-test: supporting surface=rest_api assertions=videos-generate.change.same-video-next-version
def test_only_new_or_changed_clips_are_generated_and_billed_on_a_change():
    first = AudioSession([SPEECH, MUSIC])
    original, _s, _k = _run(_request(), _stream(GOOD), first, FakeGenerator())
    edited = [{**SPEECH, "text": "A new line."}, MUSIC, {**SOUND, "id": "knock-2"}]
    session, generator = AudioSession(edited), FakeGenerator()
    video, _stages, kinds = _run(_request(previous_audio=original.audio), _stream(GOOD), session, generator)
    assert generator.generated_ids == ["voice-1", "knock-2"]  # changed narration and the new effect; music reused
    assert kinds == [("speech", "sound")]
    assert sorted(clip.kind for clip in video.audio_generated) == ["sound", "speech"]
    assert [item.clip.id for item in video.audio] == ["voice-1", "bed", "knock-2"]
    assert video.audio[1].clip.data == b"music-bytes"


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_equal_clips_of_one_plan_are_generated_once_and_hash_ignores_id_start_and_volume():
    plan = build_audio_plan([SPEECH, {**SPEECH, "id": "voice-2", "from": 100, "volume": 0.5}], PLAN_VIDEO)
    assert clip_hash(plan.entries[0], 30) == clip_hash(plan.entries[1], 30)
    generator = FakeGenerator()
    step = AudioStep(secrets_manager=None, generate=generator)
    prepared = asyncio.run(step.prepare(plan))
    assert generator.generated_ids == ["voice-1"] and len(step.generated) == 1
    assert [clip.id for clip in prepared.generated.clips] == ["voice-1", "voice-2"]
    assert isinstance(prepared.used[0], UsedClip)


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
@pytest.mark.parametrize("snippet", [
    "import {Audio} from 'remotion';",
    "import {AbsoluteFill, Html5Audio, staticFile} from 'remotion';",
])
def test_author_written_audio_is_rejected_with_a_pointer_to_the_audio_export(snippet):
    code = GOOD.replace("import {fade}", snippet + "\nimport {fade}")
    with pytest.raises(InvalidCompositionError, match="`audio` export"):
        validate_source(code, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
@pytest.mark.parametrize("element", ["<Audio src={staticFile('inputs/x.mp3')} />", "<audio src='x.mp3' />"])
def test_author_written_audio_elements_are_rejected(element):
    code = GOOD.replace("<AbsoluteFill>\n", f"<AbsoluteFill>\n    {element}\n", 1)
    with pytest.raises(InvalidCompositionError, match="`audio` export"):
        validate_source(code, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_the_audio_export_itself_and_plain_text_mentions_are_allowed():
    code = GOOD.replace("export default Main;", "export const audio = [{id: 'v', kind: 'speech', text: 'Audio check', "
                        "from: 0}] as const;\n\nexport default Main;")
    assert validate_source(code, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)["fps"] == 30
