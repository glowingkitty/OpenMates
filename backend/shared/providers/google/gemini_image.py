# backend/shared/providers/google/gemini_image.py
#
# Google Gemini image generation client using google-genai SDK.
#
# Supports two modes:
#   TEXT-TO-IMAGE  → prompt only, no reference images
#   IMAGE-TO-IMAGE → prompt + optional reference image bytes
#     The model (gemini-3-pro-image-preview) handles both modes via the same
#     generateContent endpoint. Reference images are passed as inline_data Parts
#     alongside the text Part in the contents list.
#
# Pricing (from https://ai.google.dev/gemini-api/docs/pricing):
#   Input text/image: $2.00/M tokens ($0.0011 per reference image at 560 tokens each)
#   Output image: $120/M tokens ($0.134 per 1K/2K image at 1120 tokens)
#   Adding reference images adds ~$0.0011/image to the $0.134 output cost — negligible.
#   We charge a flat 200 credits/image regardless of reference images.

import logging
import os
from typing import List, Optional

from google import genai
from google.genai import types

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Google AI Studio (Gemini API) API key
GOOGLE_AI_STUDIO_SECRET_PATH = "kv/data/providers/google_ai_studio"
GOOGLE_AI_STUDIO_API_KEY_NAME = "api_key"
_google_ai_studio_api_key: Optional[str] = None


def _get_non_empty_env(key: str) -> Optional[str]:
    """Helper to get non-empty environment variable."""
    value = os.environ.get(key)
    if not value:
        return None
    value = value.strip()
    if not value or value == "IMPORTED_TO_VAULT":
        return None
    return value


async def _get_google_ai_studio_api_key(secrets_manager: Optional[SecretsManager]) -> Optional[str]:
    """
    Retrieve Google AI Studio (Gemini API) key.
    Priority matches google_client.py
    """
    global _google_ai_studio_api_key

    if _google_ai_studio_api_key:
        return _google_ai_studio_api_key

    # 1) GEMINI_API_KEY or 2) SECRET__GOOGLE_AI_STUDIO__API_KEY env vars
    env_key = _get_non_empty_env("GEMINI_API_KEY") or _get_non_empty_env("SECRET__GOOGLE_AI_STUDIO__API_KEY")
    if env_key:
        _google_ai_studio_api_key = env_key
        return _google_ai_studio_api_key

    if not secrets_manager:
        return None

    # 3) Vault: kv/data/providers/google_ai_studio key api_key
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=GOOGLE_AI_STUDIO_SECRET_PATH,
            secret_key=GOOGLE_AI_STUDIO_API_KEY_NAME,
        )
        if api_key:
            _google_ai_studio_api_key = api_key
        return api_key
    except Exception as e:
        logger.error(f"Error retrieving Google AI Studio API key for image generation: {e}", exc_info=True)
        return None


async def generate_image_google(
    prompt: str,
    secrets_manager: SecretsManager,
    aspect_ratio: str = "1:1",
    model_id: str = "gemini-3-pro-image-preview",
    reference_image_bytes_list: Optional[List[bytes]] = None,
    reference_image_mime_types: Optional[List[str]] = None,
) -> bytes:
    """
    Generate an image using Google GenAI SDK (Gemini 3 Pro Image).

    Supports both text-to-image and image-to-image (reference-guided) generation
    using the same generateContent endpoint. Reference images are passed as inline
    Part objects alongside the text prompt.

    Args:
        prompt: The text prompt for generation or editing instruction
        secrets_manager: For API key retrieval
        aspect_ratio: Desired aspect ratio ("1:1", "16:9", etc.)
        model_id: Specific model version
        reference_image_bytes_list: Optional list of raw image bytes for reference.
                                     When provided, these are passed as inline image
                                     parts alongside the prompt. Supports up to 14
                                     reference images per the Gemini API docs.
        reference_image_mime_types: Optional MIME types for each reference image.
                                     Defaults to "image/webp" if not provided
                                     (our standard storage format).

    Returns:
        Raw image bytes (usually PNG)
    """
    # Fetch API key using logic consistent with google_client.py
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        logger.error("Google AI Studio API key not found")
        raise Exception("Google AI Studio API key not configured")

    has_reference_images = bool(reference_image_bytes_list)
    mode = "image-to-image" if has_reference_images else "text-to-image"
    ref_count = len(reference_image_bytes_list) if reference_image_bytes_list else 0
    logger.info(
        f"Generating {mode} with Gemini ({model_id}), "
        f"{ref_count} reference image(s): '{prompt[:50]}...'"
    )

    try:
        # Initialize client
        client = genai.Client(api_key=api_key)

        # Build the parts list: start with the text prompt, then add reference images.
        # Order matters: Gemini interprets the text as instructions applied to the images.
        parts: list = [types.Part.from_text(text=prompt)]

        if has_reference_images and reference_image_bytes_list:
            for idx, img_bytes in enumerate(reference_image_bytes_list):
                # Determine MIME type: use provided type, fallback to webp
                if reference_image_mime_types and idx < len(reference_image_mime_types):
                    mime_type = reference_image_mime_types[idx]
                else:
                    mime_type = "image/webp"

                parts.append(
                    types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                )

        contents = [
            types.Content(
                role="user",
                parts=parts,
            ),
        ]

        # Tools for Google Search grounding (enhances contextual understanding)
        tools = [
            types.Tool(google_search=types.GoogleSearch()),
        ]

        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(  # type: ignore[call-arg]
                image_size="1K",
                aspect_ratio=aspect_ratio,
            ),
            tools=tools,
        )

        # Execute generation
        image_data = b""

        # Using generate_content (non-streaming)
        response = client.models.generate_content(
            model=model_id,
            contents=contents,  # type: ignore[arg-type]
            config=generate_content_config,
        )

        if not response.candidates:
            raise Exception("Gemini returned empty response candidates")

        candidate = response.candidates[0]
        candidate_content = candidate.content
        if not candidate_content or not candidate_content.parts:
            raise Exception("Gemini returned candidate with no content parts")

        for part in candidate_content.parts:
            if part.inline_data:
                image_data = part.inline_data.data
                break

        if not image_data:
            # Fallback check for text response
            text_resp = response.text
            if text_resp:
                raise Exception(f"Gemini returned text instead of image: {text_resp}")
            raise Exception("No image data found in Gemini response")

        logger.info(
            f"Successfully generated {mode} with Gemini "
            f"({len(image_data)} bytes)"
        )
        return image_data

    except Exception as e:
        logger.error(f"Error during Gemini image generation: {str(e)}", exc_info=True)
        raise e
