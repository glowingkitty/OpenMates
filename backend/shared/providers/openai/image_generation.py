# backend/shared/providers/openai/image_generation.py
#
# OpenAI image generation provider wrapper for GPT Image models.
# Converts OpenMates image skill arguments into OpenAI Images API calls and
# returns raw raster bytes for the shared image storage pipeline.
#
# Pricing is configured in backend/providers/openai.yml. This wrapper does not
# calculate charges; it only returns provider output for successful calls.

import base64
import io
import logging
from typing import List, Optional

from openai import AsyncOpenAI

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

OPENAI_SECRET_PATH = "kv/data/providers/openai"
GPT_IMAGE_2_MODEL = "gpt-image-2"
OPENAI_IMAGE_SIZE_SQUARE = "1024x1024"
OPENAI_IMAGE_SIZE_PORTRAIT = "1024x1536"
OPENAI_IMAGE_SIZE_LANDSCAPE = "1536x1024"


async def _get_openai_api_key(secrets_manager: SecretsManager) -> str:
    api_key = await secrets_manager.get_secret(
        secret_path=OPENAI_SECRET_PATH,
        secret_key="api_key",
    )
    if not api_key:
        logger.error("OpenAI API key not found in Secrets Manager at kv/data/providers/openai")
        raise Exception("OpenAI API key not configured")
    return api_key


def _aspect_ratio_to_openai_size(aspect_ratio: str) -> str:
    if aspect_ratio in {"16:9", "4:3", "3:2"}:
        return OPENAI_IMAGE_SIZE_LANDSCAPE
    if aspect_ratio in {"9:16", "3:4", "2:3"}:
        return OPENAI_IMAGE_SIZE_PORTRAIT
    return OPENAI_IMAGE_SIZE_SQUARE


def _quality_to_openai_quality(quality: str) -> str:
    if quality == "max":
        return "high"
    if quality == "low":
        return "low"
    return "medium"


def _extract_image_bytes(response: object) -> bytes:
    data = getattr(response, "data", None)
    if not data:
        raise Exception("OpenAI image API returned no image data")

    first_image = data[0]
    b64_json = getattr(first_image, "b64_json", None)
    if not b64_json and isinstance(first_image, dict):
        b64_json = first_image.get("b64_json")
    if not b64_json:
        raise Exception("OpenAI image API returned no base64 image data")

    return base64.b64decode(b64_json)


async def generate_image_openai(
    prompt: str,
    secrets_manager: SecretsManager,
    *,
    model_id: str = GPT_IMAGE_2_MODEL,
    aspect_ratio: str = "1:1",
    quality: str = "default",
    reference_image_bytes_list: Optional[List[bytes]] = None,
    reference_image_mime_types: Optional[List[str]] = None,
) -> bytes:
    """
    Generate or edit a raster image via OpenAI GPT Image models.

    GPT Image 2 is token-priced, so OpenMates bills conservatively via the
    model pricing config. Reference images use the edit endpoint when present.
    """
    api_key = await _get_openai_api_key(secrets_manager)
    client = AsyncOpenAI(api_key=api_key)
    size = _aspect_ratio_to_openai_size(aspect_ratio)
    openai_quality = _quality_to_openai_quality(quality)

    logger.info(
        "Generating image with OpenAI %s, size=%s, quality=%s: '%s...'",
        model_id,
        size,
        openai_quality,
        prompt[:60],
    )

    if reference_image_bytes_list:
        image_files = []
        for idx, image_bytes in enumerate(reference_image_bytes_list):
            mime_type = (reference_image_mime_types or [])[idx] if reference_image_mime_types and idx < len(reference_image_mime_types) else "image/png"
            extension = "jpg" if mime_type == "image/jpeg" else "png"
            image_file = io.BytesIO(image_bytes)
            image_file.name = f"reference-{idx}.{extension}"
            image_files.append(image_file)

        response = await client.images.edit(
            model=model_id,
            image=image_files,
            prompt=prompt,
            size=size,
            quality=openai_quality,
            n=1,
        )
        return _extract_image_bytes(response)

    response = await client.images.generate(
        model=model_id,
        prompt=prompt,
        size=size,
        quality=openai_quality,
        n=1,
    )
    return _extract_image_bytes(response)
