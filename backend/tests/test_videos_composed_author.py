"""Composed videos of videos.generate: module contract, author messages, correction loop, fallback and billing data.

Specification: feature.app-skill.videos-generate (videos-generate.composed.author-writes-composition,
videos-generate.composed.sandbox-render-and-correction, videos-generate.billing.metered). Models and the
sandbox are fakes; the real author models and E2B template are proven by
backend/scripts/test_videos_composed.py on the dev stack.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import struct
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.apps.videos.composed.author import compose_video
from backend.apps.videos.composed.contract import (
    InvalidCompositionError,
    build_timeline,
    extract_source,
    thumbnail_frame,
    validate_source,
)
from backend.apps.videos.composed.models import (
    ComposedInput,
    ComposedInputError,
    ComposedRequest,
    ComposeFailure,
)
from backend.apps.videos.composed.prompt import (
    SYSTEM_PROMPT,
    build_author_message,
    build_correction_message,
    mp4_duration_seconds,
)
from backend.apps.videos.composed.source import build_clip_join_source, render_source_directly
from backend.tests.provider_catalogue_support import repo_provider_catalogue  # noqa: F401 - pytest fixture
from backend.shared.providers.e2b_remotion_renderer import (
    INSTALLED_FONT_FAMILIES,
    RemotionCheck,
    RemotionCompositionError,
    RemotionRender,
    RemotionSandboxError,
)

GOOD = """import React from 'react';
import {AbsoluteFill, Img, Sequence, staticFile} from 'remotion';
import {fade} from '@remotion/transitions/fade';

export const video = {fps: 30, durationInFrames: 240, width: 1280, height: 720};
export const parts = [
  {id: 'title', label: 'Title', from: 0, durationInFrames: 90, kind: 'text', texts: {title: 'OpenMates'}},
  {id: 'photo-1', label: 'Photo', from: 90, durationInFrames: 150, kind: 'image', texts: {caption: 'Hi'}},
] as const;

const Main: React.FC = () => (
  <AbsoluteFill>
    <Sequence from={parts[0].from} durationInFrames={parts[0].durationInFrames}>{parts[0].texts.title}</Sequence>
    <Sequence from={parts[1].from} durationInFrames={parts[1].durationInFrames}>
      <Img src={staticFile('inputs/input-1.png')} />
    </Sequence>
  </AbsoluteFill>
);

export default Main;
"""
VIDEO = {"fps": 30, "durationInFrames": 240, "width": 1280, "height": 720}
PARTS = [{"id": "title", "label": "Title", "from": 0, "durationInFrames": 90, "kind": "text",
          "texts": {"title": "OpenMates"}},
         {"id": "photo-1", "label": "Photo", "from": 90, "durationInFrames": 150, "kind": "image",
          "texts": {"caption": "Hi"}}]


def _png(size=(1600, 900), colour="navy") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _mp4(seconds: float) -> bytes:
    """Minimal ftyp + moov/mvhd (version 0) with timescale 1000."""
    mvhd_body = bytes(4) + struct.pack(">IIII", 0, 0, 1000, round(seconds * 1000)) + bytes(80)
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    return struct.pack(">I4s", 16, b"ftyp") + b"isom" + bytes(4) + moov


PICTURE = ComposedInput(name="input-1.png", content=_png(), mime_type="image/png", width=1600, height=900,
                        title="Sunrise over Lisbon", kind="search_result")
CLIP = ComposedInput(name="clip-1.mp4", content=_mp4(4.0), mime_type="video/mp4", width=1280, height=720,
                     kind="video_clip")


def _request(**overrides) -> ComposedRequest:
    values = {"instructions": "8 second teaser: title OpenMates, then the photo with a caption",
              "aspect_ratio": "16:9", "duration_seconds": 8, "inputs": (PICTURE,)}
    values.update(overrides)
    return ComposedRequest(**values)


def _stream(*answers, usage=(100, 400), fail_models=()):
    """Fake provider stream: one scripted answer per successful call, then usage."""
    calls = []

    async def stream_fn(**kwargs):
        calls.append(kwargs)
        if kwargs["model_id"] in fail_models:
            raise RuntimeError("provider down")
        served = len([call for call in calls if call["model_id"] not in fail_models])
        yield answers[min(served - 1, len(answers) - 1)]
        yield SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1])

    stream_fn.calls = calls
    return stream_fn


class FakeSession:
    """Scripted RemotionSession: each ``check`` / ``render`` call pops the next outcome."""

    def __init__(self, checks=(), renders=(), start_error=None):
        self.checks = list(checks)
        self.renders = list(renders)
        self.start_error = start_error
        self.entered = self.killed = False
        self.uploaded = None
        self.sources: list[str] = []
        self.frames: list[int] = []

    async def __aenter__(self):
        if self.start_error:
            raise self.start_error
        self.entered = True
        return self

    async def __aexit__(self, *_):
        self.killed = True

    async def upload_inputs(self, assets):
        self.uploaded = [(asset.name, asset.data) for asset in assets]

    async def check(self, source):
        self.sources.append(source)
        outcome = self.checks.pop(0) if self.checks else RemotionCheck(VIDEO, PARTS, 12.0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def render(self, frame):
        self.frames.append(frame)
        outcome = self.renders.pop(0) if self.renders else RemotionRender(b"mp4", b"png", 30.0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _compose(request, stream, session, **kwargs):
    stages: list[str] = []

    async def on_stage(stage):
        stages.append(stage)

    result = asyncio.run(compose_video(request, secrets_manager=None, task_id="t1", on_stage=on_stage,
                                       stream_fn=stream, session_factory=lambda: session, **kwargs))
    return result, stages


# --- module contract -------------------------------------------------------------------------------------------

# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_extract_source_takes_the_fenced_module_with_a_default_export():
    assert extract_source(f"Here you go:\n```tsx\n{GOOD}```\nDone") == GOOD
    assert extract_source(GOOD) == GOOD
    assert extract_source("```tsx\nexport const video = {};\n```") is None


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_valid_composition_passes_the_static_checks():
    assert validate_source(GOOD, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8) == VIDEO


@pytest.mark.parametrize("change, message", [
    (("from 'remotion';", "from 'remotion';\nimport axios from 'axios';"), "import of 'axios' is not allowed"),
    (("from 'remotion';", "from 'remotion';\nimport {loadFont} from '@remotion/google-fonts/Inter';"),
     "@remotion/google-fonts"),
    (("from 'remotion';", "from 'remotion';\nimport x from './other';"), "one file"),
    (("const Main", "fetch('https://example.org/a.json');\nconst Main"), "fetch"),
    (("const Main", "const n = Math.random();\nconst Main"), "random('<seed>')"),
    (("const Main", "const u = 'https://example.org/a.png';\nconst Main"), "remote address"),
    (("const Main", "const p = process.env.KEY;\nconst Main"), "process"),
    (("const Main", "const m = import('remotion');\nconst Main"), "dynamic import"),
    (("const Main", "const s = {transition: 'opacity 0.3s'};\nconst Main"), "interpolate() or spring()"),
    (("export const parts", "const parts"), "export const parts"),
    (("export default Main;", ""), "export default"),
    (("inputs/input-1.png", "inputs/input-9.png"), "not one of the given files"),
    (("width: 1280, height: 720", "width: 720, height: 1280"), "16:9 needs width 1280"),
    (("durationInFrames: 240,", "durationInFrames: 300,"), "exactly 8 s"),
    (("durationInFrames: 240,", "durationInFrames: 30 * 8,"), "plain whole-number literal"),
    (("fps: 30", "fps: 60"), "fps must be 30"),
])
# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_static_checks_reject_contract_violations(change, message):
    source = GOOD.replace(*change)
    with pytest.raises(InvalidCompositionError, match=re.escape(message)):
        validate_source(source, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_static_checks_reject_oversize_and_secrets():
    with pytest.raises(InvalidCompositionError, match="at most"):
        validate_source(GOOD + "//" + "x" * 60_000, input_names=["input-1.png"], aspect_ratio="16:9",
                        duration_seconds=8)
    with pytest.raises(InvalidCompositionError, match="secret"):
        validate_source(GOOD + "// sk-" + "a" * 30, input_names=["input-1.png"], aspect_ratio="16:9",
                        duration_seconds=8)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_static_file_paths_in_expressions_must_name_given_files():
    ternary = GOOD.replace("staticFile('inputs/input-1.png')", "staticFile(i ? 'inputs/input-1.png' : 'inputs/a.png')")
    validate_source(ternary, input_names=["input-1.png", "a.png"], aspect_ratio="16:9", duration_seconds=8)
    with pytest.raises(InvalidCompositionError, match="'inputs/a.png'"):
        validate_source(ternary, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)
    template = GOOD.replace("staticFile('inputs/input-1.png')", "staticFile(`fonts/${name}`)")
    with pytest.raises(InvalidCompositionError, match="must start with inputs/"):
        validate_source(template, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_timeline_groups_parts_by_track_in_time_order():
    parts = PARTS + [{"id": "logo", "label": "Logo", "from": 30, "durationInFrames": 60, "kind": "image",
                      "track": "overlay"}]
    timeline = build_timeline(VIDEO, list(reversed(parts)), declared=VIDEO)
    assert timeline["fps"] == 30 and timeline["duration_in_frames"] == 240
    assert (timeline["width"], timeline["height"]) == (1280, 720)
    main, overlay = sorted(timeline["tracks"], key=lambda track: track["id"] != "main")
    assert main["name"] == "Scenes" and main["kind"] == "visual"
    assert [part["id"] for part in main["parts"]] == ["title", "photo-1"]
    assert main["parts"][0] == {"id": "title", "label": "Title", "from": 0, "duration_in_frames": 90, "kind": "text",
                                "texts": [{"id": "title", "value": "OpenMates"}]}
    assert overlay["id"] == "overlay" and overlay["parts"][0]["texts"] == []
    assert thumbnail_frame(timeline) == 45


@pytest.mark.parametrize("parts, message", [
    ([], "non-empty"),
    ([PARTS[0], dict(PARTS[0])], "used twice"),
    ([{**PARTS[0], "durationInFrames": 300}], "outside the video"),
    ([{**PARTS[0], "kind": "audio"}], "kind must be one of"),
    ([{**PARTS[0], "texts": {"title": 5}}], "must be a string"),
    ([{**PARTS[0], "id": "has space"}], "short identifier"),
    (None, "non-empty array"),
])
# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_timeline_validation_rejects_bad_parts(parts, message):
    with pytest.raises(InvalidCompositionError, match=message):
        build_timeline(VIDEO, parts)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_timeline_must_match_the_declared_video():
    with pytest.raises(InvalidCompositionError, match="differs from its declaration"):
        build_timeline({**VIDEO, "durationInFrames": 300}, PARTS, declared=VIDEO)


# --- author messages -------------------------------------------------------------------------------------------

# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_author_message_carries_request_format_inputs_and_reduced_pictures():
    big = ComposedInput(name="input-2.jpg", content=_png((3000, 4000)), mime_type="image/png", width=3000,
                        height=4000, title="upload.jpg")
    message = build_author_message(instructions="Make a teaser", aspect_ratio="9:16", duration_seconds=None,
                                   inputs=[PICTURE, big, CLIP], previews=[b"a", b"b", None],
                                   previous_source=None)
    text = message["content"][0]["text"]
    assert "Request: Make a teaser" in text
    assert "width 720, height 1280, fps 30" in text and "choose a fitting length" in text
    assert "staticFile('inputs/input-1.png'): picture from a search result, 1600 x 900 px (landscape), " \
           "title 'Sunrise over Lisbon'; attached copy 1" in text
    assert "staticFile('inputs/input-2.jpg'): picture, 3000 x 4000 px (portrait)" in text
    assert "staticFile('inputs/clip-1.mp4'): video clip (mp4), 1280 x 720 px, 4.00 s (120 frames)" in text
    images = [block for block in message["content"] if block["type"] == "image_url"]
    assert [block["image_url"]["url"] for block in images] == [
        "data:image/jpeg;base64," + base64.b64encode(value).decode() for value in (b"a", b"b")]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_author_message_for_a_change_includes_the_previous_composition_and_exact_length():
    message = build_author_message(instructions="Make the title red", aspect_ratio="16:9", duration_seconds=8,
                                   inputs=[], previews=[], previous_source=GOOD)
    text = message["content"][0]["text"]
    assert "exactly 8 s = durationInFrames 240" in text
    assert "Existing composition to change" in text and "export const parts" in text
    assert "No input files" in text


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_previews_sent_to_the_author_are_reduced_jpegs():
    big = ComposedInput(name="input-1.png", content=_png((3000, 2000)), mime_type="image/png", width=3000,
                        height=2000)
    stream = _stream(GOOD)
    session = FakeSession()
    _compose(_request(inputs=(big,)), stream, session)
    image_block = [block for block in stream.calls[0]["message_history"][0]["content"]
                   if block["type"] == "image_url"][0]
    raw = base64.b64decode(image_block["image_url"]["url"].split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as preview:
        assert preview.format == "JPEG" and max(preview.size) == 1024
    assert session.uploaded == [("input-1.png", big.content)]  # the sandbox gets the full-size file


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_correction_message_is_trimmed_and_redacted():
    error = "e" * 5000 + " token sk-" + "b" * 30
    message = build_correction_message(stage="check", error=error)
    assert message["content"].startswith("Bundling or loading the composition failed")
    assert "<redacted>" in message["content"] and "sk-" not in message["content"]
    assert len(message["content"]) < 3300


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_system_prompt_states_the_contract_and_offline_fonts():
    for needle in ("export const video", "export const parts", "export default", "staticFile('inputs/",
                   "extrapolateLeft: 'clamp'", "random('<seed>')", "OffthreadVideo", "objectFit", "Series"):
        assert needle in SYSTEM_PROMPT
    assert all(family in SYSTEM_PROMPT for family in INSTALLED_FONT_FAMILIES)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_mp4_duration_is_read_from_the_movie_header():
    assert mp4_duration_seconds(_mp4(6.5)) == 6.5
    assert mp4_duration_seconds(b"not an mp4") is None


# --- author loop -----------------------------------------------------------------------------------------------

# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_first_valid_composition_is_rendered_and_billed():
    stream = _stream(f"```tsx\n{GOOD}```", usage=(1200, 900))
    session = FakeSession()
    video, stages = _compose(_request(), stream, session)
    assert stages == ["writing", "rendering"]
    assert video.mp4 == b"mp4" and video.thumbnail_png == b"png" and video.source == GOOD
    assert video.filename == "Composition.tsx" and video.attempts == 1
    assert (video.fps, video.width, video.height, video.duration_in_frames) == (30, 1280, 720, 240)
    assert video.timeline["tracks"][0]["parts"][1]["texts"] == [{"id": "caption", "value": "Hi"}]
    assert video.author_model == "google/gemini-3.8-flash"
    assert [(u.model, u.provider, u.input_tokens, u.output_tokens) for u in video.usage] == [
        ("google/gemini-3.8-flash", "google", 1200, 900)]
    assert video.sandbox_seconds == (42.0,)
    assert session.frames == [45] and session.killed
    call = stream.calls[0]
    assert call["private_logging"] is True and call["system_prompt"] == SYSTEM_PROMPT


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_build_error_goes_back_to_the_author_and_the_correction_renders():
    stream = _stream(GOOD.replace("as const;", "as const"), GOOD)
    session = FakeSession(checks=[RemotionCompositionError("check", "SyntaxError: Unexpected token (7:2)", 9.0)])
    video, stages = _compose(_request(), stream, session)
    assert stages == ["writing", "rendering", "correcting", "rendering"]
    assert video.attempts == 2 and [u.step for u in video.usage] == ["writing", "correcting"]
    assert video.sandbox_seconds == (9.0, 42.0)
    correction = stream.calls[1]["message_history"]
    assert correction[1]["role"] == "assistant" and "as const" in correction[1]["content"]
    assert "SyntaxError: Unexpected token (7:2)" in correction[2]["content"]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_static_violation_is_corrected_without_using_the_sandbox():
    stream = _stream(GOOD.replace("from 'remotion';", "from 'remotion';\nimport axios from 'axios';"), GOOD)
    session = FakeSession()
    video, _stages = _compose(_request(), stream, session)
    assert video.attempts == 2 and len(session.sources) == 1
    assert "import of 'axios' is not allowed" in stream.calls[1]["message_history"][2]["content"]
    assert video.sandbox_seconds == (42.0,)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_invalid_timeline_counts_as_a_failed_round():
    bad = RemotionCheck(VIDEO, [{**PARTS[0], "durationInFrames": 500}], 5.0)
    stream = _stream(GOOD)
    session = FakeSession(checks=[bad])
    video, _stages = _compose(_request(), stream, session)
    assert video.attempts == 2
    assert "outside the video" in stream.calls[1]["message_history"][2]["content"]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_three_failed_rounds_end_without_a_video_and_the_sandbox_is_killed():
    stream = _stream(GOOD)
    session = FakeSession(renders=[RemotionCompositionError("render", "TypeError: x is undefined", 20.0)] * 3)
    with pytest.raises(ComposeFailure) as caught:
        _compose(_request(), stream, session, models=("openai/gpt-6.1-sol",))
    assert caught.value.code == "render_failed"
    assert len(stream.calls) == 3 and session.killed


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_answers_without_a_module_fail_as_no_valid_composition():
    stream = _stream("I cannot do that.")
    session = FakeSession()
    with pytest.raises(ComposeFailure) as caught:
        _compose(_request(), stream, session, models=("a/one", "b/two"))
    assert caught.value.code == "no_valid_composition"
    assert len(stream.calls) == 2 and session.sources == [] and session.killed


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_provider_failure_falls_back_to_the_next_model():
    stream = _stream(GOOD, fail_models=("google/gemini-3.8-flash",))
    video, _stages = _compose(_request(), stream, FakeSession())
    assert video.author_model == "openai/gpt-6.1-sol"
    assert [(u.model, u.provider) for u in video.usage] == [("openai/gpt-6.1-sol", "openai")]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_all_providers_failing_is_author_unavailable():
    stream = _stream(GOOD, fail_models=("a/one", "b/two"))
    session = FakeSession()
    with pytest.raises(ComposeFailure) as caught:
        _compose(_request(), stream, session, models=("a/one", "b/two"))
    assert caught.value.code == "author_unavailable" and session.sources == []


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_sandbox_that_cannot_start_is_sandbox_unavailable():
    session = FakeSession(start_error=RemotionSandboxError("template_missing", "missing"))
    with pytest.raises(ComposeFailure) as caught:
        _compose(_request(), _stream(GOOD), session)
    assert caught.value.code == "sandbox_unavailable"


@pytest.mark.parametrize("overrides, message", [
    ({"instructions": "   "}, "empty"),
    ({"aspect_ratio": "4:3"}, "not supported"),
    ({"duration_seconds": 90}, "between 2 and 60"),
    ({"inputs": (PICTURE, PICTURE)}, "own file name"),
    ({"inputs": (ComposedInput("a.png", b"", "image/png", 1, 1),)}, "empty"),
])
# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_requests_outside_the_limits_fail_before_any_model_call(overrides, message):
    stream = _stream(GOOD)
    with pytest.raises(ComposedInputError, match=message):
        _compose(_request(**overrides), stream, FakeSession())
    assert stream.calls == []


# --- compositions built by code ----------------------------------------------------------------------------------

def _declared_parts(source: str) -> list[dict]:
    return json.loads(re.search(r"export const parts = (\[[\s\S]*?\n\]) as const;", source).group(1))


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_clip_join_source_satisfies_the_module_contract():
    clips = [{"name": "clip-1.mp4", "duration_in_frames": 240, "trim_before_frames": 0, "trim_after_frames": 30,
              "label": "Opening"},
             {"name": "clip-2.mp4", "duration_in_frames": 120, "trim_before_frames": 15, "trim_after_frames": 0,
              "label": "Extension"}]
    source = build_clip_join_source(clips)
    declared = validate_source(source, input_names=["clip-1.mp4", "clip-2.mp4"], aspect_ratio="16:9",
                               duration_seconds=None)
    assert declared == {"fps": 30, "durationInFrames": 315, "width": 1280, "height": 720}
    assert "OffthreadVideo" in source and "<Series>" in source and '"trimAfter": 210' in source
    timeline = build_timeline(declared, _declared_parts(source), declared=declared)
    parts = timeline["tracks"][0]["parts"]
    assert [(p["id"], p["label"], p["from"], p["duration_in_frames"], p["kind"]) for p in parts] == [
        ("clip-1", "Opening", 0, 210, "clip"), ("clip-2", "Extension", 210, 105, "clip")]


@pytest.mark.parametrize("clips, message", [
    ([], "at least one clip"),
    ([{"name": "../x.mp4", "duration_in_frames": 90}], "unsafe"),
    ([{"name": "a.mp4", "duration_in_frames": 90, "trim_before_frames": 90}], "trimmed away"),
    ([{"name": "a.mp4", "duration_in_frames": 30}], "at least 2 seconds"),
    ([{"name": "a.mp4", "duration_in_frames": 1900}], "at most 60 s"),
])
# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_clip_join_rejects_bad_clips(clips, message):
    with pytest.raises(ComposedInputError, match=message):
        build_clip_join_source(clips)


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_render_source_directly_renders_once_without_an_author():
    source = build_clip_join_source([{"name": "clip-1.mp4", "duration_in_frames": 120}], aspect_ratio="9:16")
    check = RemotionCheck({"fps": 30, "durationInFrames": 120, "width": 720, "height": 1280},
                          _declared_parts(source), 8.0)
    session = FakeSession(checks=[check])
    clip = ComposedInput(name="clip-1.mp4", content=_mp4(4.0), mime_type="video/mp4", width=720, height=1280,
                         kind="video_clip")
    video = asyncio.run(render_source_directly(source, [clip], secrets_manager=None, task_id="t",
                                               session_factory=lambda: session))
    assert video.usage == () and video.author_model == "" and video.attempts == 1
    assert video.sandbox_seconds == (38.0,) and session.killed
    assert video.timeline["tracks"][0]["parts"][0]["kind"] == "clip"


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_render_source_directly_fails_without_correction():
    session = FakeSession(renders=[RemotionCompositionError("render", "boom", 3.0)])
    with pytest.raises(ComposeFailure) as caught:
        asyncio.run(render_source_directly(GOOD, [PICTURE], secrets_manager=None, task_id="t",
                                           session_factory=lambda: session))
    assert caught.value.code == "render_failed" and session.killed


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_one_request_makes_at_most_three_author_calls_and_renders_across_all_models():
    stream = _stream(GOOD)
    session = FakeSession(renders=[RemotionCompositionError("render", "TypeError: x is undefined", 20.0)] * 9)
    with pytest.raises(ComposeFailure):
        _compose(_request(), stream, session, models=("a/one", "b/two", "c/three"))
    assert len(stream.calls) == 3 and len(session.frames) <= 3


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_models_that_never_answer_with_a_composition_share_the_same_budget():
    stream = _stream("no module here")
    with pytest.raises(ComposeFailure):
        _compose(_request(), stream, FakeSession(), models=("a/one", "b/two", "c/three", "d/four"))
    assert len(stream.calls) == 3


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_import_scan_ignores_from_clauses_inside_comments():
    source = GOOD.replace("export const video", "import x /* from 'remotion' */ from 'fs';\nexport const video", 1)
    with pytest.raises(InvalidCompositionError, match="'fs'"):
        validate_source(source, input_names=["input-1.png"], aspect_ratio="16:9", duration_seconds=8)


# --- user AI settings ------------------------------------------------------------------------------------------

USER_MODEL = "anthropic/claude-fable-5-2"


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
def test_default_policy_keeps_the_default_model_order_and_adds_no_stream_options():
    from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy

    stream = _stream(GOOD)
    _compose(_request(), stream, FakeSession(), models=("a/one", "b/two"), policy=InternalLlmPolicy())
    assert [call["model_id"] for call in stream.calls] == ["a/one"]
    assert "allowed_server_ids" not in stream.calls[0]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
@pytest.mark.usefixtures("repo_provider_catalogue")
def test_users_complex_model_alone_writes_the_composition():
    from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy

    stream = _stream(GOOD)
    video, _ = _compose(_request(), stream, FakeSession(), models=("a/one", "b/two"),
                        policy=InternalLlmPolicy(complex_model=USER_MODEL))
    assert {call["model_id"] for call in stream.calls} == {USER_MODEL}
    assert video.author_model == USER_MODEL
    assert [(u.model, u.provider) for u in video.usage] == [(USER_MODEL, "anthropic")]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
@pytest.mark.usefixtures("repo_provider_catalogue")
def test_turned_off_default_model_is_skipped():
    from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy

    stream = _stream(GOOD)
    _compose(_request(), stream, FakeSession(), models=(USER_MODEL, "openai/gpt-6.1-sol"),
             policy=InternalLlmPolicy(disabled_ai_models=frozenset({USER_MODEL})))
    assert [call["model_id"] for call in stream.calls] == ["openai/gpt-6.1-sol"]


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.author-writes-composition
@pytest.mark.usefixtures("repo_provider_catalogue")
def test_every_model_turned_off_fails_before_any_call():
    from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy

    stream = _stream(GOOD)
    policy = InternalLlmPolicy(disabled_ai_models=frozenset({"a/one", "b/two"}))
    with pytest.raises(ComposeFailure) as caught:
        _compose(_request(), stream, FakeSession(), models=("a/one", "b/two"), policy=policy)
    assert caught.value.code == "author_unavailable" and "turned off" in caught.value.message
    assert stream.calls == []
