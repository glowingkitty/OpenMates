"""Compositions built by code and rendering an existing composition without an author.

``build_clip_join_source`` writes the deterministic composition that plays
mp4 clips one after another (a ``<Series>`` of ``<OffthreadVideo>``), used
when a generated clip is extended or trimmed; it satisfies the same module
contract as an authored composition, so its timeline comes out of the same
sandbox check. ``render_source_directly`` renders such a source (or a kept
composition) in the sandbox with no author call; a failure is not corrected
and raises ``ComposeFailure("render_failed")``.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from backend.apps.videos.composed.audio_step import AudioStep
from backend.apps.videos.composed.contract import FPS, FORMATS, MAX_FRAMES, MAX_LABEL_CHARS
from backend.apps.videos.composed.models import ComposedInput, ComposedInputError, ComposedVideo, ComposeFailure
from backend.apps.videos.composed.rounds import RoundFailed, SandboxRunner, SessionFactory, default_session_factory
from backend.shared.providers.e2b_remotion_renderer import SAFE_INPUT_NAME, SOURCE_FILENAME

_CLIP_JOIN_TEMPLATE = """import React from 'react';
import {{AbsoluteFill, OffthreadVideo, Series, staticFile}} from 'remotion';

export const video = {{fps: {fps}, durationInFrames: {total}, width: {width}, height: {height}}};

export const parts = {parts} as const;

const clips = {clips} as const;

const Main: React.FC = () => (
  <AbsoluteFill style={{{{backgroundColor: 'black'}}}}>
    <Series>
      {{clips.map((clip, index) => (
        <Series.Sequence key={{parts[index].id}} durationInFrames={{parts[index].durationInFrames}}>
          <OffthreadVideo
            src={{staticFile(`inputs/${{clip.name}}`)}}
            trimBefore={{clip.trimBefore}}
            trimAfter={{clip.trimAfter}}
            style={{{{width: '100%', height: '100%', objectFit: 'contain'}}}}
          />
        </Series.Sequence>
      ))}}
    </Series>
  </AbsoluteFill>
);

export default Main;
"""


def _whole(value: Any, name: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ComposedInputError(f"{name} must be a whole number of at least {minimum}")
    return value


def build_clip_join_source(clips: list[dict], *, aspect_ratio: str = "16:9") -> str:
    """Composition that plays the clips in order, each trimmed by frames at its start and end.

    Every clip is ``{name, duration_in_frames, trim_before_frames, trim_after_frames, label}``:
    ``duration_in_frames`` is the clip's full length at 30 fps and the trims are the frames cut
    away at its start and at its end.
    """
    if not clips:
        raise ComposedInputError("at least one clip is needed")
    if aspect_ratio not in FORMATS:
        raise ComposedInputError(f"aspect ratio {aspect_ratio!r} is not supported")
    width, height = FORMATS[aspect_ratio]
    parts, plays, start = [], [], 0
    for index, clip in enumerate(clips, start=1):
        name = clip.get("name")
        if not isinstance(name, str) or not SAFE_INPUT_NAME.match(name) or ".." in name:
            raise ComposedInputError(f"clip {index} has an unsafe file name")
        full = _whole(clip.get("duration_in_frames"), f"clip {index} duration_in_frames", minimum=1)
        before = _whole(clip.get("trim_before_frames", 0), f"clip {index} trim_before_frames", minimum=0)
        after = _whole(clip.get("trim_after_frames", 0), f"clip {index} trim_after_frames", minimum=0)
        visible = full - before - after
        if visible < 1:
            raise ComposedInputError(f"clip {index} is trimmed away completely")
        label = str(clip.get("label") or f"Clip {index}").strip()[:MAX_LABEL_CHARS] or f"Clip {index}"
        parts.append({"id": f"clip-{index}", "label": label, "from": start, "durationInFrames": visible,
                      "kind": "clip", "texts": {}})
        plays.append({"name": name, "trimBefore": before, "trimAfter": full - after})
        start += visible
    if start > MAX_FRAMES:
        raise ComposedInputError(f"the joined clips last {start / FPS:.1f} s; at most {MAX_FRAMES // FPS} s are allowed")
    if start < 2 * FPS:
        raise ComposedInputError("the joined clips must last at least 2 seconds")
    return _CLIP_JOIN_TEMPLATE.format(fps=FPS, total=start, width=width, height=height,
                                      parts=json.dumps(parts, ensure_ascii=False, indent=2),
                                      clips=json.dumps(plays, indent=2))


async def render_source_directly(
    source: str, inputs: Sequence[ComposedInput], *, secrets_manager: Any, task_id: str,
    session_factory: Optional[SessionFactory] = None,
) -> ComposedVideo:
    """Render an existing composition once, with no author call and no correction."""
    runner = SandboxRunner(session_factory or default_session_factory(secrets_manager), inputs,
                           AudioStep(secrets_manager=secrets_manager))
    try:
        result = await runner.run(source, aspect_ratio=None, duration_seconds=None)
    except RoundFailed as exc:
        raise ComposeFailure("render_failed", f"[{task_id}] {exc.stage}: {exc.error[-1000:]}") from exc
    finally:
        await runner.close()
    timeline = result.timeline
    return ComposedVideo(
        mp4=result.render.mp4, thumbnail_png=result.render.thumbnail_png, source=source, filename=SOURCE_FILENAME,
        timeline=timeline, fps=timeline["fps"], width=timeline["width"], height=timeline["height"],
        duration_in_frames=timeline["duration_in_frames"], attempts=1, author_model="", usage=(),
        sandbox_seconds=tuple(runner.sandbox_seconds),
    )
