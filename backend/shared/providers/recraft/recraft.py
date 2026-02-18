# backend/shared/providers/recraft/recraft.py
#
# Recraft V4 API client for vector (SVG) image generation.
#
# Recraft is the only production-grade AI model capable of generating true SVG
# vector graphics from text prompts. Used when output_filetype="svg" is requested.
#
# API docs: https://www.recraft.ai/docs/api-reference/endpoints
# Pricing:
#   - recraftv4_vector:     $0.08/image → 80 credits  (default quality)
#   - recraftv4_pro_vector: $0.30/image → 300 credits (max quality, 4MP)
#
# Authentication: Bearer token stored in Vault at kv/data/providers/recraft

import logging
import httpx
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Recraft API base URL (OpenAI-compatible REST interface)
RECRAFT_API_BASE = "https://external.api.recraft.ai/v1"

# Model IDs for vector generation
RECRAFT_MODEL_DEFAULT = "recraftv4_vector"      # 1MP, $0.08/image — default quality
RECRAFT_MODEL_MAX = "recraftv4_pro_vector"      # 4MP, $0.30/image — max quality


async def generate_vector_recraft(
    prompt: str,
    secrets_manager: SecretsManager,
    model_id: str = RECRAFT_MODEL_DEFAULT,
    size: str = "1:1",
) -> bytes:
    """
    Generate an SVG vector image using the Recraft V4 API.

    Calls POST /v1/images/generations with a vector model, fetches the resulting
    SVG file from the returned URL, and returns the raw SVG bytes.

    Args:
        prompt:          Text description of the desired vector image.
        secrets_manager: SecretsManager instance for Vault API key retrieval.
        model_id:        Recraft model to use. One of:
                           - "recraftv4_vector"     (default, 1MP, $0.08)
                           - "recraftv4_pro_vector" (max quality, 4MP, $0.30)
        size:            Aspect ratio in "w:h" format (e.g. "1:1", "16:9").
                         Recraft accepts both "WxH" and "w:h" — we pass "w:h" directly.

    Returns:
        Raw SVG bytes from the Recraft API.

    Raises:
        Exception: If the API key is missing, the API returns an error, or the
                   image URL cannot be fetched.
    """
    # Retrieve API key from Vault
    api_key = await secrets_manager.get_secret("kv/data/providers/recraft", "api_key")
    if not api_key:
        logger.error("Recraft API key not found in Secrets Manager at kv/data/providers/recraft")
        raise Exception("Recraft API key not configured")

    logger.info(
        f"Generating SVG vector with Recraft ({model_id}), size={size}: '{prompt[:60]}...'"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # POST /v1/images/generations — generate image and get back a URL
    payload = {
        "prompt": prompt,
        "model": model_id,
        "size": size,
        "response_format": "url",  # returns {"data": [{"url": "..."}]}
        "n": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{RECRAFT_API_BASE}/images/generations",
                json=payload,
                headers=headers,
            )

            if response.status_code != 200:
                error_detail = response.text
                logger.error(
                    f"Recraft API error (status {response.status_code}): {error_detail}"
                )
                raise Exception(
                    f"Recraft API error {response.status_code}: {error_detail}"
                )

            data = response.json()
            images = data.get("data", [])

            if not images:
                raise Exception("Recraft API returned no images in response")

            image_url = images[0].get("url")
            if not image_url:
                raise Exception("Recraft API returned no image URL in response")

            # Fetch the SVG file from the returned URL
            logger.info(f"Fetching SVG from Recraft URL: {image_url[:80]}...")
            svg_response = await client.get(image_url, timeout=60.0)
            svg_response.raise_for_status()

            svg_bytes = svg_response.content
            logger.info(
                f"Successfully generated SVG vector with Recraft ({model_id}): "
                f"{len(svg_bytes)} bytes"
            )
            return svg_bytes

    except httpx.TimeoutException as e:
        logger.error(f"Recraft API request timed out: {e}", exc_info=True)
        raise Exception(f"Recraft API timed out: {e}") from e
    except Exception as e:
        logger.error(f"Error during Recraft vector generation: {e}", exc_info=True)
        raise
