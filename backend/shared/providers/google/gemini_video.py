# backend/shared/providers/google/gemini_video.py
#
# Google Veo video generation provider for OpenMates.
# Uses the official Gemini API long-running video generation endpoint and
# downloads the generated MP4 before app-level encryption/storage. Provider code
# stays pure: no skill, embed, S3, or billing dependencies here.

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

GOOGLE_AI_STUDIO_SECRET_PATH = "kv/data/providers/google_ai_studio"
GOOGLE_AI_STUDIO_API_KEY_NAME = "api_key"
GEMINI_VIDEO_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_VEO_MODEL = "veo-3.1-generate-preview"
POLL_INTERVAL_SECONDS = 10
MAX_POLL_SECONDS = 420

_google_ai_studio_api_key: Optional[str] = None


@dataclass(frozen=True)
class GeneratedVideo:
    """Normalized Google Veo video generation response."""

    video_bytes: bytes
    mime_type: str
    model: str
    duration_seconds: int
    resolution: str
    aspect_ratio: str


def _get_non_empty_env(key: str) -> Optional[str]:
    value = os.environ.get(key)
    if not value:
        return None
    value = value.strip()
    if not value or value == "IMPORTED_TO_VAULT":
        return None
    return value


async def _get_google_ai_studio_api_key(secrets_manager: Optional[SecretsManager]) -> Optional[str]:
    global _google_ai_studio_api_key
    if _google_ai_studio_api_key:
        return _google_ai_studio_api_key

    env_key = _get_non_empty_env("GEMINI_API_KEY") or _get_non_empty_env("SECRET__GOOGLE_AI_STUDIO__API_KEY")
    if env_key:
        _google_ai_studio_api_key = env_key
        return _google_ai_studio_api_key

    if not secrets_manager:
        return None

    api_key = await secrets_manager.get_secret(
        secret_path=GOOGLE_AI_STUDIO_SECRET_PATH,
        secret_key=GOOGLE_AI_STUDIO_API_KEY_NAME,
    )
    if api_key:
        _google_ai_studio_api_key = api_key
    return api_key


async def generate_video_google_veo(
    *,
    prompt: str,
    secrets_manager: SecretsManager,
    model_id: str = DEFAULT_VEO_MODEL,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 8,
    resolution: str = "720p",
    seed: Optional[int] = None,
) -> GeneratedVideo:
    """Generate a video with Google Veo via the Gemini API long-running operation."""
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        raise RuntimeError("Google AI Studio API key is not configured for Veo video generation")

    normalized_model = model_id or DEFAULT_VEO_MODEL
    duration = max(4, min(int(duration_seconds or 8), 8))
    if duration not in {4, 6, 8}:
        duration = 8
    normalized_aspect_ratio = aspect_ratio if aspect_ratio in {"16:9", "9:16"} else "16:9"
    normalized_resolution = resolution if resolution in {"720p", "1080p", "4k"} else "720p"

    parameters: dict[str, object] = {
        "aspectRatio": normalized_aspect_ratio,
        "durationSeconds": str(duration),
        "resolution": normalized_resolution,
        "numberOfVideos": 1,
        "personGeneration": "allow_all",
    }
    if seed is not None:
        parameters["seed"] = int(seed)

    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        start_response = await client.post(
            f"{GEMINI_VIDEO_API_BASE_URL}/models/{normalized_model}:predictLongRunning",
            headers=headers,
            json={"instances": [{"prompt": prompt}], "parameters": parameters},
        )
        start_response.raise_for_status()
        operation_name = start_response.json().get("name")
        if not operation_name:
            raise RuntimeError(f"Veo generation did not return an operation name: {start_response.text[:300]}")

        elapsed = 0
        operation_payload = {}
        while elapsed <= MAX_POLL_SECONDS:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS
            poll_response = await client.get(f"{GEMINI_VIDEO_API_BASE_URL}/{operation_name}", headers=headers)
            poll_response.raise_for_status()
            operation_payload = poll_response.json()
            if operation_payload.get("done"):
                break
        else:
            raise TimeoutError(f"Veo generation did not complete within {MAX_POLL_SECONDS} seconds")

        if operation_payload.get("error"):
            raise RuntimeError(f"Veo generation failed: {operation_payload['error']}")

        samples = (
            operation_payload.get("response", {})
            .get("generateVideoResponse", {})
            .get("generatedSamples", [])
        )
        video_uri = samples[0].get("video", {}).get("uri") if samples else None
        if not video_uri:
            raise RuntimeError(f"Veo operation returned no video URI: {str(operation_payload)[:500]}")

        video_response = await client.get(video_uri, headers={"x-goog-api-key": api_key})
        video_response.raise_for_status()
        video_bytes = video_response.content
        if not video_bytes:
            raise RuntimeError("Veo returned an empty video file")

    return GeneratedVideo(
        video_bytes=video_bytes,
        mime_type="video/mp4",
        model=normalized_model,
        duration_seconds=duration,
        resolution=normalized_resolution,
        aspect_ratio=normalized_aspect_ratio,
    )
