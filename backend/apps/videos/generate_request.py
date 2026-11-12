"""Request contract of the videos.generate skill (Specification feature.app-skill.videos-generate).

``parse_generate_request`` is the single validation of one request item. The
skill runs it before anything is queued and the task runs it again on the
queued arguments, so a call outside the limits fails explicitly before any
model, sandbox or charge is involved.

``check_route_constraints`` applies the limits that depend on how the video is
made (generative clip or composed video); the task calls it once the route is
known (from the request's mode or from the routing decision).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional

MAX_INSTRUCTION_CHARS = 4000
MAX_IMAGES = 12
MODES = ("auto", "generative", "composed")
MODE_AUTO, MODE_GENERATIVE, MODE_COMPOSED = MODES
ASPECT_RATIOS = ("16:9", "9:16", "1:1")
GENERATIVE_ASPECT_RATIOS = ("16:9", "9:16")
DEFAULT_ASPECT_RATIO = "16:9"
GENERATIVE_MIN_SECONDS = 3
GENERATIVE_MAX_SECONDS = 15
GENERATIVE_DEFAULT_SECONDS = 8
EXTEND_MAX_SECONDS = 10  # an added clip (extend_start / extend_end) lasts 3-10 seconds
COMPOSED_MIN_SECONDS = 2
COMPOSED_MAX_SECONDS = 60
RESOLUTIONS = ("360p", "480p", "720p", "1080p", "4k")
OMNI_RESOLUTIONS = ("360p", "720p", "1080p", "4k")
DEFAULT_RESOLUTION = "720p"
CHANGES = ("edit", "extend_start", "extend_end")
DEFAULT_CHANGE = "edit"

H3_MODEL = "minimax/h3-max-turbo/image-to-video"
OMNI_MODEL = "gemini-omni-1.2-flash"
DEFAULT_MODEL = OMNI_MODEL
VALID_MODELS = frozenset({H3_MODEL, OMNI_MODEL})

ONE_PICTURE_MESSAGE = (
    "A generative clip can start from one picture only; a composed video (mode composed) can use several pictures."
)


class GenerateRequestError(ValueError):
    """The call is outside the request contract; nothing is queued, run or charged."""

    def __init__(self, message: str, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GenerateRequest:
    """One validated request item of a videos.generate call."""

    instructions: str
    images: tuple[str, ...]
    mode: str
    aspect_ratio: str
    duration_seconds: Optional[int]
    resolution: Optional[str]
    model: Optional[str]
    seed: Optional[int]
    source_video: Optional[str]
    change: Optional[str]
    first_frame_embed_ids: tuple[str, ...]

    @property
    def is_change(self) -> bool:
        return self.source_video is not None


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise GenerateRequestError(f"{field} must be text")
    return value.strip()


def _optional_int(value: Any, field: str) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise GenerateRequestError(f"{field} must be a whole number")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        value = int(value.strip())
    if not isinstance(value, int):
        raise GenerateRequestError(f"{field} must be a whole number")
    return value


def _choice(value: Any, allowed: tuple[str, ...], field: str, default: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return default
    text = str(value).strip().lower() if field != "aspect_ratio" else str(value).strip()
    if text not in allowed:
        raise GenerateRequestError(f"{field} must be one of {', '.join(allowed)}")
    return text


def _refs(images: Any) -> tuple[str, ...]:
    if images is None:
        return ()
    if not isinstance(images, (list, tuple)):
        raise GenerateRequestError("images must be a list of exact embed_refs of pictures in this chat")
    if len(images) > MAX_IMAGES:
        raise GenerateRequestError(f"at most {MAX_IMAGES} pictures can be used in one video")
    refs: list[str] = []
    for value in images:
        if not isinstance(value, str) or not value.strip():
            raise GenerateRequestError("every entry of images must be the exact embed_ref of a picture in this chat")
        refs.append(value.strip())
    return tuple(refs)


def _first_frame_ids(value: Any) -> tuple[str, ...]:
    """The former ``input_embed_ids`` field: at most one first-frame image UUID (generative path)."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > 1:
        raise GenerateRequestError("Provide at most one first-frame input_embed_ids image")
    try:
        return tuple(str(uuid.UUID(str(item))) for item in value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise GenerateRequestError("First-frame input_embed_ids must contain image embed UUIDs") from exc


def parse_generate_request(item: Mapping[str, Any]) -> GenerateRequest:
    """Validate one request item; raise ``GenerateRequestError`` with a plain reason."""
    if not isinstance(item, Mapping):
        raise GenerateRequestError("every request must be an object")
    raw_instructions = item.get("instructions")
    if raw_instructions in (None, ""):
        raw_instructions = item.get("prompt")  # former name of the field
    instructions = _text(raw_instructions, "instructions") if raw_instructions is not None else ""
    if not instructions:
        raise GenerateRequestError("instructions are required: describe the video in natural language")
    if len(instructions) > MAX_INSTRUCTION_CHARS:
        raise GenerateRequestError(f"instructions are longer than {MAX_INSTRUCTION_CHARS} characters")

    images = _refs(item.get("images"))
    first_frame_ids = _first_frame_ids(item.get("input_embed_ids"))
    if images and first_frame_ids:
        raise GenerateRequestError("pass pictures either as images (embed_refs) or as input_embed_ids, not both")
    mode = _choice(item.get("mode"), MODES, "mode", MODE_AUTO) or MODE_AUTO
    aspect_ratio = _choice(item.get("aspect_ratio"), ASPECT_RATIOS, "aspect_ratio", DEFAULT_ASPECT_RATIO)
    duration = _optional_int(item.get("duration_seconds"), "duration_seconds")
    if duration is not None and not COMPOSED_MIN_SECONDS <= duration <= COMPOSED_MAX_SECONDS:
        raise GenerateRequestError(
            f"duration_seconds must be between {COMPOSED_MIN_SECONDS} and {COMPOSED_MAX_SECONDS} seconds"
        )
    resolution = _choice(item.get("resolution"), RESOLUTIONS, "resolution", None)
    model_value = item.get("model")
    model = str(model_value).strip() if model_value not in (None, "") else None
    if model is not None and model not in VALID_MODELS:
        raise GenerateRequestError(f"model must be one of {', '.join(sorted(VALID_MODELS))}")
    seed = _optional_int(item.get("seed"), "seed")

    source_value = item.get("source_video")
    source_video = _text(source_value, "source_video") or None if source_value not in (None, "") else None
    change = _choice(item.get("change"), CHANGES, "change", None)
    if change is not None and source_video is None:
        raise GenerateRequestError("change needs source_video: the embed_ref of the video to change")
    if source_video is not None and change is None:
        change = DEFAULT_CHANGE
    if source_video is not None:
        check_change_constraints(GenerateRequest(
            instructions=instructions, images=images, mode=mode, aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
            duration_seconds=duration, resolution=resolution, model=model, seed=seed, source_video=source_video,
            change=change, first_frame_embed_ids=first_frame_ids,
        ))
    if first_frame_ids and mode == MODE_COMPOSED:
        raise GenerateRequestError("input_embed_ids is a generative first frame; pass composed pictures as images")
    if mode == MODE_AUTO and (model is not None or first_frame_ids):
        # A named video model or a legacy first-frame id only exists on the generative route.
        mode = MODE_GENERATIVE

    request = GenerateRequest(
        instructions=instructions, images=images, mode=mode, aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
        duration_seconds=duration, resolution=resolution, model=model, seed=seed, source_video=source_video,
        change=change, first_frame_embed_ids=first_frame_ids,
    )
    if mode != MODE_AUTO:
        check_route_constraints(request, mode)
    return request


def check_route_constraints(request: GenerateRequest, route: str) -> None:
    """Limits that depend on the route; raise ``GenerateRequestError`` when the request cannot be made that way."""
    if route == MODE_COMPOSED:
        if request.model is not None:
            raise GenerateRequestError("model selects a generative video model; a composed video has none")
        if request.first_frame_embed_ids:
            raise GenerateRequestError("input_embed_ids is a generative first frame; pass composed pictures as images")
        return
    if route != MODE_GENERATIVE:
        raise ValueError(f"unknown video route {route!r}")
    if len(request.images) > 1:
        raise GenerateRequestError(ONE_PICTURE_MESSAGE, code="generative_needs_one_picture")
    if request.aspect_ratio not in GENERATIVE_ASPECT_RATIOS:
        raise GenerateRequestError("a generative clip is 16:9 or 9:16; use mode composed for a square video")
    if request.duration_seconds is not None and not (
            GENERATIVE_MIN_SECONDS <= request.duration_seconds <= GENERATIVE_MAX_SECONDS):
        raise GenerateRequestError(
            f"a generative clip lasts {GENERATIVE_MIN_SECONDS} to {GENERATIVE_MAX_SECONDS} seconds; use mode "
            "composed for other lengths")
    if generative_model(request) == OMNI_MODEL and request.resolution not in (None, *OMNI_RESOLUTIONS):
        raise GenerateRequestError(f"a Gemini Omni clip is {', '.join(OMNI_RESOLUTIONS)}")


def check_change_constraints(request: GenerateRequest) -> None:
    """Limits of a change: an added clip lasts 3-10 seconds (format and size come from the video itself)."""
    if request.change in ("extend_start", "extend_end") and request.duration_seconds is not None and not (
            GENERATIVE_MIN_SECONDS <= request.duration_seconds <= EXTEND_MAX_SECONDS):
        raise GenerateRequestError(
            f"an added clip lasts {GENERATIVE_MIN_SECONDS} to {EXTEND_MAX_SECONDS} seconds")


def generative_model(request: GenerateRequest) -> str:
    """The generative model of a request: the named one, else Gemini Omni (a given picture is its first frame)."""
    return request.model or DEFAULT_MODEL


def check_external_request(request: GenerateRequest) -> None:
    """The developer REST API offers text-only generative video; everything else needs the chat's embed context."""
    if request.images or request.first_frame_embed_ids:
        raise GenerateRequestError("pictures need the chat's embed context and are not available through the REST API",
                                   code="not_available_via_api")
    if request.mode == MODE_COMPOSED:
        raise GenerateRequestError("composed videos are not available through the REST API",
                                   code="not_available_via_api")
    if request.source_video is not None:
        raise GenerateRequestError("changing a video is not available through the REST API",
                                   code="not_available_via_api")
    if request.model == H3_MODEL:
        raise GenerateRequestError(
            "H3 video generation is available in authenticated chats and calls; REST generation currently supports "
            "Gemini Omni only", code="not_available_via_api",
        )
    check_route_constraints(request, MODE_GENERATIVE)


def task_arguments(request: GenerateRequest) -> dict[str, Any]:
    """The request fields as queued task arguments (the task parses them again)."""
    return {
        "instructions": request.instructions,
        "prompt": request.instructions,
        "images": list(request.images),
        "mode": request.mode,
        "aspect_ratio": request.aspect_ratio,
        "duration_seconds": request.duration_seconds,
        "resolution": request.resolution,
        "model": request.model,
        "seed": request.seed,
        "source_video": request.source_video,
        "change": request.change,
        "first_frame_embed_ids": list(request.first_frame_embed_ids),
    }
