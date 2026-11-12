"""The composition module contract: extraction, static checks and timeline validation.

A composition is one TSX module that imports only ``remotion``, ``react`` and
the first-party ``@remotion/*`` packages installed in the template, exports
``video`` (plain literals: fps 30, at most 60 s, one of the fixed sizes),
``parts`` (plain timeline data whose ``texts`` the component renders) and a
default React component, and reads pictures only through
``staticFile("inputs/<name>")``. The static check here is cheap and runs
before any sandbox time; it is not the security boundary - the offline
sandbox is. The timeline is never parsed from the text: the sandbox bundles
the module and reports its exported ``video`` and ``parts``, which
``build_timeline`` validates and turns into the stored timeline.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from backend.apps.videos.composed.models import ComposedInputError
from backend.shared.providers.e2b_remotion_renderer import COMPOSITION_PACKAGES, MAX_SOURCE_CHARS, SECRET_PATTERNS

FPS = 30
MIN_SECONDS = 2
MAX_SECONDS = 60
MAX_FRAMES = FPS * MAX_SECONDS
FORMATS: dict[str, tuple[int, int]] = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
PART_KINDS = frozenset({"scene", "clip", "text", "image"})
MAX_PARTS = 60
MAX_TEXT_CHARS = 600
MAX_LABEL_CHARS = 80
DEFAULT_TRACK = "main"
DEFAULT_TRACK_NAME = "Scenes"

_FENCE = re.compile(r"```(?:tsx|typescript|ts|jsx|javascript|js)?[ \t]*\n([\s\S]*?)```", re.IGNORECASE)
_IMPORT_FROM = re.compile(r"^\s*(?:import|export)\b[^;'\"]*?\bfrom\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_BARE_IMPORT = re.compile(r"^\s*import\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_VIDEO_EXPORT = re.compile(r"export\s+const\s+video\s*(?::\s*[\w.<>\[\] ]+)?=\s*\{([^{}]*)\}")
_VIDEO_FIELD = re.compile(r"\b(fps|durationInFrames|width|height)\s*:\s*([^,}]+)")
_STATIC_FILE = re.compile(r"staticFile\s*\(\s*([\s\S]{0,200}?)\)")
_STRING_LITERAL = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")
_TEMPLATE_LITERAL = re.compile(r"`([^`]*)`")
_URL = re.compile(r"\b(?:https?|wss?|ftp)://[^\s'\"`)]+", re.IGNORECASE)
_ALLOWED_URL_PREFIXES = ("http://www.w3.org/",)  # SVG/XLink namespaces only
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FORBIDDEN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfetch\s*\("), "network requests (fetch) are not allowed; use only the given input files"),
    (re.compile(r"\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b|\bsendBeacon\b"),
     "network APIs are not allowed; use only the given input files"),
    (re.compile(r"\bimport\s*\("), "dynamic import() is not allowed"),
    (re.compile(r"\brequire\s*\("), "require() is not allowed; use static imports"),
    (re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(\s*['\"`]"), "eval and new Function are not allowed"),
    (re.compile(r"\bprocess\s*\.|\bprocess\s*\["), "process is not available in a composition"),
    (re.compile(r"\bMath\s*\.\s*random\b"), "Math.random() makes renders differ; use random('<seed>') from remotion"),
    (re.compile(r"\b(?:localStorage|sessionStorage|indexedDB|document\.cookie)\b"), "browser storage is not allowed"),
    (re.compile(r"\bDate\s*\.\s*now\s*\(|\bnew\s+Date\s*\(\s*\)|\bperformance\s*\.\s*now\s*\("),
     "the current time makes renders differ; derive everything from useCurrentFrame()"),
    (re.compile(r"\bsetTimeout\s*\(|\bsetInterval\s*\(|\brequestAnimationFrame\s*\("),
     "timers do not run in frame order; derive animation from useCurrentFrame()"),
    (re.compile(r"\b(?:animation|transition)\s*:\s*['\"`][^'\"`]*\d+m?s"),
     "CSS animations and transitions are not rendered frame by frame; use interpolate() or spring()"),
)


class InvalidCompositionError(ValueError):
    """The authored text breaks the module contract; the message goes back to the author."""


def frame_size(aspect_ratio: str) -> tuple[int, int]:
    """Exact pixel size of a supported aspect ratio."""
    if aspect_ratio not in FORMATS:
        raise ComposedInputError(f"aspect ratio {aspect_ratio!r} is not supported; use one of {', '.join(FORMATS)}")
    return FORMATS[aspect_ratio]


def extract_source(text: str) -> Optional[str]:
    """Return the TSX module in model output (a fenced block or the whole answer), if it has a default export."""
    fenced = [block.strip() for block in _FENCE.findall(text or "")]
    candidates = fenced or [(text or "").strip()]
    for code in sorted(candidates, key=len, reverse=True):
        if re.search(r"^\s*export\s+default\b", code, re.MULTILINE):
            return code + "\n"
    return None


def _package_of(specifier: str) -> str:
    if specifier.startswith("@"):
        return "/".join(specifier.split("/")[:2])
    return specifier.split("/", 1)[0]


def _declared_video(code: str) -> dict[str, int]:
    match = _VIDEO_EXPORT.search(code)
    if not match:
        raise InvalidCompositionError("the module must declare `export const video = {fps: 30, durationInFrames: "
                                      "<frames>, width: <px>, height: <px>}` with plain number literals")
    fields = dict(_VIDEO_FIELD.findall(match.group(1)))
    video: dict[str, int] = {}
    for key in ("fps", "durationInFrames", "width", "height"):
        value = fields.get(key, "").strip()
        if not re.fullmatch(r"\d{1,5}", value):
            raise InvalidCompositionError(f"video.{key} must be a plain whole-number literal, found "
                                          f"{value or 'nothing'!r}")
        video[key] = int(value)
    return video


def check_video(video: dict[str, Any], *, aspect_ratio: Optional[str], duration_seconds: Optional[int]) -> None:
    """Enforce fps, length and frame size limits of the declared ``video``."""
    fps, frames = video.get("fps"), video.get("durationInFrames")
    width, height = video.get("width"), video.get("height")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (fps, frames, width, height)):
        raise InvalidCompositionError("video.fps, durationInFrames, width and height must be whole numbers")
    if fps != FPS:
        raise InvalidCompositionError(f"video.fps must be {FPS}, not {fps}")
    if not FPS * MIN_SECONDS <= frames <= MAX_FRAMES:
        raise InvalidCompositionError(f"video.durationInFrames is {frames}; it must be between {FPS * MIN_SECONDS} "
                                      f"and {MAX_FRAMES} ({MIN_SECONDS}-{MAX_SECONDS} s at {FPS} fps)")
    if duration_seconds is not None and frames != duration_seconds * FPS:
        raise InvalidCompositionError(f"the video must last exactly {duration_seconds} s: durationInFrames "
                                      f"{duration_seconds * FPS}, not {frames}")
    if aspect_ratio is None:
        if (width, height) not in FORMATS.values():
            raise InvalidCompositionError(f"video size {width}x{height} is not one of the supported sizes")
        return
    expected = frame_size(aspect_ratio)
    if (width, height) != expected:
        raise InvalidCompositionError(f"the requested format {aspect_ratio} needs width {expected[0]} and height "
                                      f"{expected[1]}, not {width}x{height}")


def _strip_comments(code: str) -> str:
    """Code without ``/* */`` and ``//`` comments (kept inside string and template literals).

    Used only for the import scan, so a ``from '...'`` inside a comment can neither hide nor fake an import.
    Regex literals are not tracked; at worst a comment-like part of one is dropped from the import scan.
    """
    out: list[str] = []
    i, size, quote = 0, len(code), ""
    while i < size:
        char = code[i]
        pair = code[i:i + 2]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < size:
                out.append(code[i + 1])
                i += 1
            elif char == quote or (char == "\n" and quote != "`"):
                quote = ""
        elif char in "'\"`":
            quote = char
            out.append(char)
        elif pair == "/*":
            end = code.find("*/", i + 2)
            i = size if end == -1 else end + 1
            out.append(" ")
        elif pair == "//":
            end = code.find("\n", i)
            i = size if end == -1 else end - 1
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _check_static_files(code: str, names: frozenset[str]) -> None:
    # Every path literal inside a staticFile(...) argument (also in a ternary) must name a given file;
    # a template literal must start with inputs/. Paths built elsewhere fail visibly in the sandbox.
    known = ", ".join(sorted(f"inputs/{name}" for name in names)) or "none"
    for argument in _STATIC_FILE.findall(code):
        for match in _STRING_LITERAL.finditer(argument):
            path = match.group(1) if match.group(1) is not None else match.group(2)
            if not path.startswith("inputs/") or path.removeprefix("inputs/") not in names:
                raise InvalidCompositionError(f"staticFile path {path!r} is not one of the given files ({known})")
        for template in _TEMPLATE_LITERAL.findall(argument):
            if not template.startswith("inputs/"):
                raise InvalidCompositionError(f"staticFile path `{template[:60]}` must start with inputs/ ({known})")


def validate_source(code: str, *, input_names: Iterable[str], aspect_ratio: Optional[str],
                    duration_seconds: Optional[int]) -> dict[str, int]:
    """Check the module contract without running it; return the declared ``video``."""
    if not code.strip():
        raise InvalidCompositionError("the composition is empty")
    if len(code) > MAX_SOURCE_CHARS:
        raise InvalidCompositionError(f"the composition is {len(code)} characters; at most {MAX_SOURCE_CHARS} "
                                      "are allowed")
    if any(pattern.search(code) for pattern in SECRET_PATTERNS):
        raise InvalidCompositionError("the composition appears to contain a secret or key")
    uncommented = _strip_comments(code)
    for specifier in _IMPORT_FROM.findall(uncommented) + _BARE_IMPORT.findall(uncommented):
        if specifier.startswith((".", "/")):
            raise InvalidCompositionError(f"import of {specifier!r} is not allowed; the composition is one file")
        if _package_of(specifier) not in COMPOSITION_PACKAGES:
            allowed = ", ".join(sorted(COMPOSITION_PACKAGES))
            raise InvalidCompositionError(f"import of {specifier!r} is not allowed; use only {allowed}")
    for pattern, message in _FORBIDDEN:
        if pattern.search(code):
            raise InvalidCompositionError(message)
    for url in _URL.findall(code):
        if not url.startswith(_ALLOWED_URL_PREFIXES):
            raise InvalidCompositionError(f"remote address {url[:80]!r} is not allowed; the renderer is offline, "
                                          "show only the given input files")
    if not re.search(r"^\s*export\s+const\s+parts\b", code, re.MULTILINE):
        raise InvalidCompositionError("the module must declare `export const parts = [...]` describing the timeline")
    if not re.search(r"^\s*export\s+default\b", code, re.MULTILINE):
        raise InvalidCompositionError("the module must `export default` its React component")
    _check_static_files(code, frozenset(input_names))
    video = _declared_video(code)
    check_video(video, aspect_ratio=aspect_ratio, duration_seconds=duration_seconds)
    return video


def _part_texts(index: int, raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise InvalidCompositionError(f"parts[{index}].texts must be an object of text key to string")
    texts = []
    for key, value in raw.items():
        if not _ID.match(str(key)):
            raise InvalidCompositionError(f"parts[{index}].texts key {key!r} must be a short identifier")
        if not isinstance(value, str) or len(value) > MAX_TEXT_CHARS:
            raise InvalidCompositionError(f"parts[{index}].texts.{key} must be a string of at most {MAX_TEXT_CHARS} "
                                          "characters")
        texts.append({"id": str(key), "value": value})
    return texts


def build_timeline(video: dict[str, Any], parts: Any, *, declared: Optional[dict[str, int]] = None) -> dict[str, Any]:
    """Validate the exported ``video``/``parts`` reported by the sandbox and return the stored timeline."""
    if declared is not None and any(video.get(key) != value for key, value in declared.items()):
        raise InvalidCompositionError("the exported video object differs from its declaration; keep video plain "
                                      "literals")
    check_video(video, aspect_ratio=None, duration_seconds=None)
    total = int(video["durationInFrames"])
    if not isinstance(parts, list) or not parts:
        raise InvalidCompositionError("parts must be a non-empty array describing every scene of the video")
    if len(parts) > MAX_PARTS:
        raise InvalidCompositionError(f"parts has {len(parts)} entries; at most {MAX_PARTS} are allowed")
    tracks: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise InvalidCompositionError(f"parts[{index}] must be an object")
        part_id, label, kind = part.get("id"), part.get("label"), part.get("kind")
        start, length = part.get("from"), part.get("durationInFrames")
        if not isinstance(part_id, str) or not _ID.match(part_id):
            raise InvalidCompositionError(f"parts[{index}].id must be a short identifier like 'intro'")
        if part_id in seen:
            raise InvalidCompositionError(f"parts id {part_id!r} is used twice; ids must be unique")
        seen.add(part_id)
        if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_CHARS:
            raise InvalidCompositionError(f"parts[{index}].label must be a short non-empty text")
        if kind not in PART_KINDS:
            raise InvalidCompositionError(f"parts[{index}].kind must be one of {', '.join(sorted(PART_KINDS))}")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (start, length)):
            raise InvalidCompositionError(f"parts[{index}].from and durationInFrames must be whole frame numbers")
        if start < 0 or length < 1 or start + length > total:
            raise InvalidCompositionError(f"parts[{index}] ({part_id}) covers frames {start}-{start + length}, "
                                          f"outside the video's {total} frames")
        track = part.get("track") or DEFAULT_TRACK
        if not isinstance(track, str) or not _ID.match(track):
            raise InvalidCompositionError(f"parts[{index}].track must be a short identifier")
        tracks.setdefault(track, []).append({
            "id": part_id, "label": label.strip(), "from": start, "duration_in_frames": length, "kind": kind,
            "texts": _part_texts(index, part.get("texts")),
        })
    return {
        "fps": int(video["fps"]), "duration_in_frames": total, "width": int(video["width"]),
        "height": int(video["height"]),
        "tracks": [{"id": track_id,
                    "name": DEFAULT_TRACK_NAME if track_id == DEFAULT_TRACK else track_id.replace("-", " ").title(),
                    "kind": "visual", "parts": sorted(items, key=lambda item: (item["from"], item["id"]))}
                   for track_id, items in tracks.items()],
    }


def thumbnail_frame(timeline: dict[str, Any]) -> int:
    """A frame that shows content: the middle of the first part, inside the video."""
    first = min((part for track in timeline["tracks"] for part in track["parts"]), key=lambda part: part["from"])
    return min(timeline["duration_in_frames"] - 1, first["from"] + first["duration_in_frames"] // 2)
