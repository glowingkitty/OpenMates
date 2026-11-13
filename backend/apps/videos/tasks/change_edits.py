"""Structured trims of a generative video, applied by code (assertion videos-generate.change.edit-mode).

The timeline's edit mode sends its pending edits as one message, one line per
edit (``buildEditRequestText`` in the web timeline model), e.g.::

    Apply these edits to this video:
    - Part "Sunrise" (id clip-1): shorten by 1.0 s at the end
    - Remove part "Harbour" (id clip-3)
    - Trim the video: remove 0.5 s from the start and 1.0 s from the end

When every line of a change to a video made of generated clips is such a trim
or removal, the new clip list is computed here and rendered as a clip join with
no author call. Anything else (a text change, free wording, a line in another
language, a part id that is not a clip of this video) returns ``None`` and the
change goes to the author model with the join composition as its starting point.
"""

from __future__ import annotations

import dataclasses
import math
import re
from typing import Optional, Sequence

from backend.apps.videos.tasks.video_kept import KeptClip

FPS = 30
INTRO_LINE = "Apply these edits to this video:"
_LABEL = r'"(?:[^"\\]|\\.)*"'
_SECONDS = r"(\d+(?:\.\d+)?)"
_SHORTEN = re.compile(rf"^- Part {_LABEL} \(id clip-(\d+)\): shorten by {_SECONDS} s at the (start|end)$")
_REMOVE = re.compile(rf"^- Remove part {_LABEL} \(id clip-(\d+)\)$")
_TRIM_BOTH = re.compile(rf"^- Trim the video: remove {_SECONDS} s from the start and {_SECONDS} s from the end$")
_TRIM_START = re.compile(rf"^- Trim the video: remove {_SECONDS} s from the start$")
_TRIM_END = re.compile(rf"^- Trim the video: remove {_SECONDS} s from the end$")


class ClipEditError(ValueError):
    """Structured edits that cannot apply to this video (they would remove all of it)."""


@dataclasses.dataclass
class _Edits:
    shorten_start: dict[int, int] = dataclasses.field(default_factory=dict)
    shorten_end: dict[int, int] = dataclasses.field(default_factory=dict)
    removed: set[int] = dataclasses.field(default_factory=set)
    video_start: int = 0
    video_end: int = 0


def _frames(seconds: str) -> int:
    return round(float(seconds) * FPS)


def _parse(instructions: str, clip_count: int) -> Optional[_Edits]:
    lines = [line.strip() for line in instructions.strip().splitlines() if line.strip()]
    if lines and lines[0] == INTRO_LINE:
        lines = lines[1:]
    if not lines:
        return None
    edits = _Edits()
    for line in lines:
        if match := _SHORTEN.match(line):
            index = int(match.group(1))
            if not 1 <= index <= clip_count:
                return None
            target = edits.shorten_start if match.group(3) == "start" else edits.shorten_end
            target[index] = target.get(index, 0) + _frames(match.group(2))
        elif match := _REMOVE.match(line):
            index = int(match.group(1))
            if not 1 <= index <= clip_count:
                return None
            edits.removed.add(index)
        elif match := _TRIM_BOTH.match(line):
            edits.video_start += _frames(match.group(1))
            edits.video_end += _frames(match.group(2))
        elif match := _TRIM_START.match(line):
            edits.video_start += _frames(match.group(1))
        elif match := _TRIM_END.match(line):
            edits.video_end += _frames(match.group(1))
        else:
            return None
    return edits


def _cut(clips: list[KeptClip], frames: int, *, at_start: bool) -> list[KeptClip]:
    """Remove ``frames`` from the start or end of the whole clip list, dropping clips cut away completely."""
    clips = list(clips)
    while frames > 0:
        if not clips:
            raise ClipEditError("the trim removes the whole video")
        edge = clips[0] if at_start else clips[-1]
        if frames >= edge.visible_frames:
            frames -= edge.visible_frames
            clips.pop(0 if at_start else -1)
            continue
        field = "trim_before_frames" if at_start else "trim_after_frames"
        trimmed = dataclasses.replace(edge, **{field: getattr(edge, field) + frames})
        clips[0 if at_start else -1] = trimmed
        frames = 0
    return clips


def apply_clip_edits(instructions: str, clips: Sequence[KeptClip]) -> Optional[tuple[KeptClip, ...]]:
    """The clips after the structured edits, or ``None`` when the change needs the author model."""
    edits = _parse(instructions, len(clips))
    if edits is None:
        return None
    result: list[KeptClip] = []
    for index, clip in enumerate(clips, start=1):
        if index in edits.removed:
            continue
        before = clip.trim_before_frames + edits.shorten_start.get(index, 0)
        after = clip.trim_after_frames + edits.shorten_end.get(index, 0)
        if clip.duration_in_frames - before - after < 1:
            raise ClipEditError(f"part clip-{index} would be shortened away completely")
        result.append(dataclasses.replace(clip, trim_before_frames=before, trim_after_frames=after))
    result = _cut(_cut(result, edits.video_start, at_start=True), edits.video_end, at_start=False)
    if not result:
        raise ClipEditError("the edits remove the whole video")
    return tuple(result)


def visible_seconds(clips: Sequence[KeptClip]) -> float:
    return sum(clip.visible_frames for clip in clips) / FPS


def clip_frames(duration_seconds: float) -> int:
    """Whole frames of a measured clip at the timeline rate."""
    return max(1, math.floor(duration_seconds * FPS))
