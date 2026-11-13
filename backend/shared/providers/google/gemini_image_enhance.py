"""Faithful higher-quality re-render of one image with Google Gemini image models.

Used by the image Enhance action (Specification feature.embed-user-edits,
assertion embed-user-edits.enhance.faithful-2k; Plan
docs/plans/embed-user-edit-versions). One call sends the source picture and a
fixed prompt to ``gemini-nano-banana-2.1`` through the official Gemini API
(``generateContent`` with ``response_modalities=["IMAGE"]``,
https://ai.google.dev/gemini-api/docs/image-generation) at the 2K output size
and the supported aspect ratio nearest to the source. No Google Search tool is
attached: the result must not draw in outside content.

This module is a pure provider wrapper. Key retrieval is shared with
``gemini_image`` (AI Studio key from the environment or Vault);
``generate_image_google`` stays unchanged. Every failure raises
``ImageEnhanceProviderError`` so the caller can fail the request without a charge.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Optional

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.google.gemini_image import _get_google_ai_studio_api_key

logger = logging.getLogger(__name__)

ENHANCE_MODEL_ID = "gemini-nano-banana-2.1"
ENHANCE_MODEL_REF = f"google/{ENHANCE_MODEL_ID}"
ENHANCE_IMAGE_SIZE = "2K"
ENHANCE_PROMPT = (
    "Re-render this exact image at higher quality. Keep the composition, subjects, poses, colours, "
    "lighting, layout and any text exactly as they are. Improve only fine detail: faces, hands, "
    "textures, edges and the legibility of text. Do not add, remove or move anything."
)
# Aspect ratios the Gemini image models accept in ``ImageConfig.aspect_ratio``.
SUPPORTED_ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
SUPPORTED_INPUT_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class ImageEnhanceProviderError(RuntimeError):
    """The provider produced no usable image; nothing may be charged for this request."""


@dataclass(frozen=True)
class EnhancedImage:
    """Raw bytes returned by the provider and the request parameters that produced them."""

    image_bytes: bytes
    mime_type: str
    model_id: str
    aspect_ratio: str
    image_size: str


def nearest_aspect_ratio(width: int, height: int) -> str:
    """Supported ratio closest to ``width:height`` on a logarithmic scale (portrait and landscape alike)."""
    if isinstance(width, bool) or isinstance(height, bool) or width <= 0 or height <= 0:
        raise ValueError("An image needs a positive width and height")
    target = math.log(width / height)

    def distance(ratio: str) -> float:
        w, h = (int(part) for part in ratio.split(":"))
        return abs(math.log(w / h) - target)

    return min(SUPPORTED_ASPECT_RATIOS, key=distance)


def _first_image_part(response: types.GenerateContentResponse) -> tuple[bytes, str]:
    for candidate in response.candidates or []:
        content = candidate.content
        for part in (content.parts if content and content.parts else []):
            inline = part.inline_data
            if inline and inline.data:
                return inline.data, str(inline.mime_type or "image/png")
    raise ImageEnhanceProviderError("Gemini returned no image for the enhance request")


async def enhance_image_google(
    *,
    image_bytes: bytes,
    mime_type: str,
    width: int,
    height: int,
    secrets_manager: Optional[SecretsManager],
    model_id: str = ENHANCE_MODEL_ID,
) -> EnhancedImage:
    """Re-render ``image_bytes`` faithfully at 2K; raise ``ImageEnhanceProviderError`` on any failure."""
    if not image_bytes:
        raise ValueError("The source image is empty")
    if mime_type not in SUPPORTED_INPUT_MIME_TYPES:
        raise ValueError(f"Unsupported source image type for enhance: {mime_type}")
    aspect_ratio = nearest_aspect_ratio(width, height)
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        raise ImageEnhanceProviderError("Google AI Studio API key is not configured")

    # Keep the client in a variable for the whole call: an inline client is closed
    # before the request finishes.
    client = genai.Client(api_key=api_key)
    contents = [types.Content(role="user", parts=[
        types.Part.from_text(text=ENHANCE_PROMPT),
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
    ])]
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(image_size=ENHANCE_IMAGE_SIZE, aspect_ratio=aspect_ratio),
    )
    logger.info("Enhancing image with %s at %s, aspect ratio %s", model_id, ENHANCE_IMAGE_SIZE, aspect_ratio)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content, model=model_id, contents=contents, config=config,
        )
    except genai_errors.APIError as exc:
        raise ImageEnhanceProviderError(f"Gemini enhance request failed with HTTP {exc.code}") from exc
    except httpx.HTTPError as exc:
        raise ImageEnhanceProviderError("Gemini enhance request did not complete") from exc
    data, output_mime = _first_image_part(response)
    return EnhancedImage(
        image_bytes=data, mime_type=output_mime, model_id=model_id,
        aspect_ratio=aspect_ratio, image_size=ENHANCE_IMAGE_SIZE,
    )
