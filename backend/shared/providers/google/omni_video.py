# backend/shared/providers/google/omni_video.py
#
# Gemini Omni video generation provider (replaces the shut-down Veo 3.1 preview
# models in the Gemini API). Pure provider wrapper: no skill, embed, S3 or
# billing imports; callers get bytes plus measured/reported facts.
#
# Verified against the official docs on 2026-11-12:
#   https://aistudio.google.com/docs/omni         (request shape, modes, limits)
#   https://aistudio.google.com/docs/video        (Veo 3.1 preview shut down 2026-10-22)
#   https://aistudio.google.com/docs/pricing      (output-token based video pricing)
#   https://aistudio.google.com/docs/deprecations (veo-3.1-* -> gemini-omni-1.2-flash)
#
# Documented behaviours used here (and nothing else):
#   - text-to-video: one text input.
#   - image-to-video: one image part (first frame) plus text.
#   - first+last frame: two image parts plus text, 3-10 s only.
#   - subject references: up to 6 images, task "reference_to_video".
#   - extend: a source video (inline base64) plus text, task "extend"; the model
#     reads the last 10 s and appends 3-10 s at the END only. Not available for
#     uploaded videos in the EEA, Switzerland and the UK.
# NOT documented, therefore rejected instead of faked: last-frame-only and
# prepending a clip that leads into a given frame.
#
# store: false by default (inline base64 delivery, nothing retained by Google).
# Verified 2026-11-12: delivery "uri" is rejected unless store=true ("store=true
# is required when response format has video delivery set to URI"), so uri
# delivery is opt-in and means Google retains the interaction/file.

import asyncio
import base64
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional, Sequence

import httpx

from backend.shared.python_utils.video_frames import (
    VideoFrameError,
    probe_video,
)

logger = logging.getLogger(__name__)

GOOGLE_AI_STUDIO_SECRET_PATH = "kv/data/providers/google_ai_studio"
GOOGLE_AI_STUDIO_API_KEY_NAME = "api_key"
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OMNI_MODEL = "gemini-omni-1.2-flash"

MIN_DURATION_SECONDS = 3
MAX_DURATION_SECONDS = 15
MAX_INTERPOLATION_SECONDS = 10
MAX_REFERENCE_IMAGES = 6
ASPECT_RATIOS = ("16:9", "9:16")
RESOLUTIONS = ("360p", "720p", "1080p", "4k")

REQUEST_TIMEOUT_SECONDS = 420.0
FILE_POLL_INTERVAL_SECONDS = 5.0
FILE_POLL_MAX_SECONDS = 120.0

Resolution = Literal["360p", "720p", "1080p", "4k"]
Delivery = Literal["uri", "inline"]


class OmniVideoError(RuntimeError):
    """Base class for Gemini Omni video failures."""


class OmniUnavailableError(OmniVideoError):
    """Provider unreachable, rate limited, overloaded, or key missing/denied."""


class OmniRegionError(OmniUnavailableError):
    """The feature is not available for the server's region (e.g. uploaded video input)."""


class OmniSafetyError(OmniVideoError):
    """The prompt/images/output were blocked by the provider's safety filters."""


class OmniInvalidArgumentError(OmniVideoError):
    """The request is invalid (rejected locally or by the provider with 400)."""


class OmniTimeoutError(OmniVideoError):
    """The provider did not answer or the file did not become ready in time."""


@dataclass(frozen=True)
class OmniImage:
    """An image input (first frame, last frame, or subject reference)."""

    data: bytes
    mime_type: str = "image/jpeg"


@dataclass(frozen=True)
class OmniVideo:
    """Generated clip. Duration/size are measured from the mp4, not requested."""

    mp4: bytes
    duration_seconds: float
    width: int
    height: int
    model: str
    input_tokens: int
    output_tokens: int
    thought_tokens: int


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "***") if api_key else text


async def _resolve_api_key(secrets_manager: Any) -> str:
    for name in ("GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value and value != "IMPORTED_TO_VAULT":
            return value
    if secrets_manager is not None:
        value = await secrets_manager.get_secret(
            secret_path=GOOGLE_AI_STUDIO_SECRET_PATH,
            secret_key=GOOGLE_AI_STUDIO_API_KEY_NAME,
        )
        if value and value != "IMPORTED_TO_VAULT":
            return value
    raise OmniUnavailableError("Google AI Studio API key is not configured")


def _image_part(image: OmniImage) -> dict[str, Any]:
    if not image.data:
        raise OmniInvalidArgumentError("image input is empty")
    return {
        "type": "image",
        "data": base64.b64encode(image.data).decode("ascii"),
        "mime_type": image.mime_type,
    }


def build_request_body(
    prompt: str,
    *,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    first_frame: Optional[OmniImage],
    last_frame: Optional[OmniImage],
    reference_images: Sequence[OmniImage],
    source_video: Optional[bytes],
    delivery: Delivery,
) -> dict[str, Any]:
    """Validate the combination and build the Interactions request body."""
    if not prompt or not prompt.strip():
        raise OmniInvalidArgumentError("prompt is required")
    if not MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS:
        raise OmniInvalidArgumentError(
            f"duration must be {MIN_DURATION_SECONDS}-{MAX_DURATION_SECONDS} seconds"
        )
    if aspect_ratio not in ASPECT_RATIOS:
        raise OmniInvalidArgumentError(f"aspect_ratio must be one of {ASPECT_RATIOS}")
    if resolution not in RESOLUTIONS:
        raise OmniInvalidArgumentError(f"resolution must be one of {RESOLUTIONS}")
    if len(reference_images) > MAX_REFERENCE_IMAGES:
        raise OmniInvalidArgumentError(f"at most {MAX_REFERENCE_IMAGES} reference images")
    if last_frame is not None and first_frame is None:
        raise OmniInvalidArgumentError(
            "a last frame without a first frame is not supported by Gemini Omni"
        )
    modes = sum(
        bool(x) for x in (first_frame, reference_images, source_video)
    )
    if modes > 1:
        raise OmniInvalidArgumentError(
            "first/last frame, reference images and a source video cannot be combined"
        )
    if last_frame is not None and duration_seconds > MAX_INTERPOLATION_SECONDS:
        raise OmniInvalidArgumentError(
            f"first+last frame clips support at most {MAX_INTERPOLATION_SECONDS} seconds"
        )
    if source_video is not None and duration_seconds > MAX_INTERPOLATION_SECONDS:
        raise OmniInvalidArgumentError("an extension adds 3-10 seconds per turn")

    parts: list[dict[str, Any]] = []
    video_config: dict[str, str] = {}
    if first_frame is not None:
        parts.append(_image_part(first_frame))
    if last_frame is not None:
        parts.append(_image_part(last_frame))
    if reference_images:
        parts.extend(_image_part(image) for image in reference_images)
        video_config["task"] = "reference_to_video"
    if source_video is not None:
        parts.append({
            "type": "video",
            "mime_type": "video/mp4",
            "data": base64.b64encode(source_video).decode("ascii"),
        })
        video_config["task"] = "extend"
    parts.append({"type": "text", "text": prompt})

    body: dict[str, Any] = {
        "model": OMNI_MODEL,
        "input": parts if len(parts) > 1 else prompt,
        "store": delivery == "uri",
        "response_format": {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration": f"{duration_seconds}s",
            **({"delivery": "uri"} if delivery == "uri" else {}),
        },
    }
    if source_video is not None:
        # Verified 2026-11-12: the API rejects aspect_ratio for the extend task
        # (the source video's ratio is kept).
        del body["response_format"]["aspect_ratio"]
    if video_config:
        body["generation_config"] = {"video_config": video_config}
    return body


def _error_from_response(response: httpx.Response, api_key: str) -> OmniVideoError:
    status = response.status_code
    message, status_name = "", ""
    try:
        error = response.json().get("error", {})
        message = str(error.get("message", ""))
        status_name = str(error.get("status", ""))
    except (ValueError, AttributeError):
        message = response.text[:200]
    detail = _redact(f"HTTP {status} {status_name}: {message[:300]}", api_key)
    lowered = message.lower()
    if "your region" in lowered or "isn't available in" in lowered:
        return OmniRegionError(detail)
    if any(word in lowered for word in ("safety", "blocked", "prohibited", "policy")):
        return OmniSafetyError(detail)
    if status in (400, 404, 422):
        return OmniInvalidArgumentError(detail)
    if status in (401, 403, 429) or status >= 500:
        return OmniUnavailableError(detail)
    return OmniVideoError(detail)


def _extract_video_item(payload: dict[str, Any]) -> dict[str, Any]:
    for step in payload.get("steps", []):
        if step.get("type") != "model_output":
            continue
        for item in step.get("content", []):
            if item.get("type") == "video" and (item.get("data") or item.get("uri")):
                return item
    status = payload.get("status")
    raise OmniSafetyError(
        f"Gemini Omni returned no video (status={status}); the request was likely "
        "blocked by safety filters"
    )


async def _download_uri(
    client: httpx.AsyncClient, uri: str, headers: dict[str, str], api_key: str
) -> bytes:
    match = re.search(r"(files/[^/:?]+)", uri)
    if match:
        deadline = time.monotonic() + FILE_POLL_MAX_SECONDS
        while True:
            meta = await client.get(f"{GEMINI_API_BASE_URL}/{match.group(1)}", headers=headers)
            if meta.status_code != 200:
                raise _error_from_response(meta, api_key)
            state = meta.json().get("state")
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise OmniUnavailableError("Gemini file processing failed")
            if time.monotonic() >= deadline:
                raise OmniTimeoutError("generated video file did not become ACTIVE")
            await asyncio.sleep(FILE_POLL_INTERVAL_SECONDS)
    response = await client.get(uri, headers=headers)
    if response.status_code != 200:
        raise _error_from_response(response, api_key)
    return response.content


async def generate_omni_video(
    prompt: str,
    *,
    duration_seconds: int,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    first_frame: Optional[bytes] = None,
    first_frame_mime: str = "image/jpeg",
    last_frame: Optional[bytes] = None,
    last_frame_mime: str = "image/jpeg",
    reference_images: Sequence[OmniImage] = (),
    source_video: Optional[bytes] = None,
    delivery: Delivery = "inline",
    secrets_manager: Any = None,
) -> OmniVideo:
    """Generate a clip with Gemini Omni via the Interactions API.

    Modes: text-to-video; first frame; first+last frame (3-10 s); reference
    images; extend (source_video, appended at the end). Last-frame-only and
    lead-in clips are not documented and raise OmniInvalidArgumentError.
    """
    body = build_request_body(
        prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        first_frame=OmniImage(first_frame, first_frame_mime) if first_frame else None,
        last_frame=OmniImage(last_frame, last_frame_mime) if last_frame else None,
        reference_images=reference_images,
        source_video=source_video,
        delivery=delivery,
    )
    api_key = await _resolve_api_key(secrets_manager)
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = await client.post(
                f"{GEMINI_API_BASE_URL}/interactions", headers=headers, json=body
            )
            if response.status_code != 200:
                raise _error_from_response(response, api_key)
            payload = response.json()
            if payload.get("status") not in (None, "completed"):
                raise OmniUnavailableError(f"interaction ended with status {payload.get('status')}")
            item = _extract_video_item(payload)
            if item.get("data"):
                mp4 = base64.b64decode(item["data"])
            else:
                mp4 = await _download_uri(client, item["uri"], {"x-goog-api-key": api_key}, api_key)
    except httpx.TimeoutException as exc:
        raise OmniTimeoutError("Gemini Omni request timed out") from exc
    except httpx.TransportError as exc:
        raise OmniUnavailableError(_redact(f"Gemini Omni unreachable: {exc}", api_key)) from exc
    if not mp4:
        raise OmniUnavailableError("Gemini Omni returned an empty video")

    try:
        info = await probe_video(mp4)
    except VideoFrameError as exc:
        raise OmniUnavailableError(f"returned video is not decodable: {exc}") from exc
    usage = payload.get("usage") or {}
    logger.info(
        "Gemini Omni clip ready: %.2fs %dx%d output_tokens=%s",
        info.duration_seconds, info.width, info.height, usage.get("total_output_tokens"),
    )
    return OmniVideo(
        mp4=mp4,
        duration_seconds=info.duration_seconds,
        width=info.width,
        height=info.height,
        model=OMNI_MODEL,
        input_tokens=int(usage.get("total_input_tokens") or 0),
        output_tokens=int(usage.get("total_output_tokens") or 0),
        thought_tokens=int(usage.get("total_thought_tokens") or 0),
    )
