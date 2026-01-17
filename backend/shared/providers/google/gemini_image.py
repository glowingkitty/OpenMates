# backend/shared/providers/google/gemini_image.py
#
# Google Gemini image generation client using google-genai SDK.

import logging
import os
from typing import Optional
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
    model_id: str = "gemini-3-pro-image-preview"
) -> bytes:
    """
    Generate an image using Google GenAI SDK (Gemini 3 Pro Image).
    
    Args:
        prompt: The text prompt for generation
        secrets_manager: For API key retrieval
        aspect_ratio: Desired aspect ratio ("1:1", "16:9", etc.)
        model_id: Specific model version
        
    Returns:
        Raw image bytes (usually PNG)
    """
    # Fetch API key using logic consistent with google_client.py
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        logger.error("Google AI Studio API key not found")
        raise Exception("Google AI Studio API key not configured")

    logger.info(f"Generating image with Gemini ({model_id}): '{prompt[:50]}...'")
    
    try:
        # Initialize client
        client = genai.Client(api_key=api_key)

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                ],
            ),
        ]
        
        # Tools for Google Search grounding
        tools = [
            types.Tool(google_search=types.GoogleSearch()),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
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
            contents=contents,
            config=generate_content_config,
        )

        if not response.candidates or not response.candidates[0].content.parts:
            raise Exception("Gemini returned empty response candidates")

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_data = part.inline_data.data
                break
        
        if not image_data:
            # Fallback check for text response
            text_resp = response.text
            if text_resp:
                raise Exception(f"Gemini returned text instead of image: {text_resp}")
            raise Exception("No image data found in Gemini response")

        logger.info(f"Successfully generated image with Gemini ({len(image_data)} bytes)")
        return image_data

    except Exception as e:
        logger.error(f"Error during Gemini image generation: {str(e)}", exc_info=True)
        raise e
