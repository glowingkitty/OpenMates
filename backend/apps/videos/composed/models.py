"""Data shapes of the composed-video engine (Specification feature.app-skill.videos-generate).

``ComposedRequest`` is what the videos.generate task hands in: the
instruction, the format and the pictures (or mp4 clips) the composition may
show, each already loaded at full size and named for the sandbox, plus the
text of every referenced search result (``ComposedInput.text`` for a result
with a picture, ``ComposedSource`` for one without). The engine
returns ``ComposedVideo`` with the MP4, its thumbnail, the final composition
source, the validated timeline and everything billing needs (author token
usage per call, wall seconds per sandbox round). ``ComposeFailure`` means no
video was produced; the caller charges nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

INPUT_KINDS = frozenset({"image", "search_result", "video_clip"})
SOURCE_KINDS = frozenset({"search_result"})
MAX_SOURCES = 24  # text-only search results of one request (a whole search expands to at most this many)
FAILURE_CODES = frozenset({"no_valid_composition", "render_failed", "sandbox_unavailable", "author_unavailable"})


@dataclass(frozen=True)
class ComposedInput:
    """One picture (or mp4 clip) handed to the composition as ``staticFile("inputs/<name>")``."""

    name: str  # file name inside the sandbox, e.g. "input-1.jpg"
    content: bytes  # full-size bytes
    mime_type: str
    width: int
    height: int
    title: str = ""  # search-result title or upload file name, shown to the author
    kind: str = "image"  # "image" | "search_result" | "video_clip"
    text: str = ""  # search result: its bounded text (source, date, URL, description); untrusted data


@dataclass(frozen=True)
class ComposedSource:
    """A referenced search result without a picture file: only its title and text reach the author."""

    title: str
    text: str  # bounded "Label: value" lines; untrusted third-party data
    kind: str = "search_result"


@dataclass(frozen=True)
class ComposedRequest:
    instructions: str
    aspect_ratio: str  # "16:9" | "9:16" | "1:1"
    duration_seconds: Optional[int]
    inputs: tuple[ComposedInput, ...]
    previous_source: Optional[str] = None  # kept composition when changing a video
    sources: tuple[ComposedSource, ...] = ()  # text-only search results, after the pictures in request order


@dataclass(frozen=True)
class AuthorUsage:
    """Token usage of one author call; ``model`` is the full model reference used for pricing."""

    model: str  # e.g. "anthropic/claude-haiku-5-5"
    provider: str  # e.g. "anthropic"
    input_tokens: int
    output_tokens: int
    step: str = "writing"  # "writing" | "correcting"


@dataclass(frozen=True)
class ComposedVideo:
    mp4: bytes
    thumbnail_png: bytes
    source: str  # final composition TSX
    filename: str  # "Composition.tsx"
    timeline: dict[str, Any]
    fps: int
    width: int
    height: int
    duration_in_frames: int
    attempts: int  # 1..3 rounds of the answering author model
    author_model: str  # "" when the source was built by code
    usage: tuple[AuthorUsage, ...] = field(default_factory=tuple)
    sandbox_seconds: tuple[float, ...] = field(default_factory=tuple)  # billed 5 credits per started minute each


class ComposedInputError(ValueError):
    """The request is outside the limits (instructions, inputs, format); nothing is run or charged."""


class ComposeFailure(RuntimeError):
    """No video was produced; ``code`` is one of ``FAILURE_CODES``. Nothing is charged."""

    def __init__(self, code: str, message: str) -> None:
        if code not in FAILURE_CODES:
            raise ValueError(f"unknown compose failure code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
