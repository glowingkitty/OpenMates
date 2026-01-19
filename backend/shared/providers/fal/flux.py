# backend/shared/providers/fal/flux.py
#
# fal.ai Flux API client for fast image generation using httpx.

import logging
import httpx
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

async def generate_image_fal_flux(
    prompt: str,
    secrets_manager: SecretsManager,
    model_id: str = "fal-ai/flux-2/klein/9b/base",
    image_size: str = "landscape_4_3"
) -> bytes:
    """
    Generate an image using fal.ai Flux API via HTTP REST.
    
    Args:
        prompt: The text prompt for generation
        secrets_manager: For API key retrieval
        model_id: Specific model path on fal.ai
        image_size: Aspect ratio / size preset (e.g., landscape_4_3, square_hd)
        
    Returns:
        Raw image bytes (PNG/JPEG/WEBP)
    """
    # Fetch API key
    api_key = await secrets_manager.get_secret("kv/data/providers/fal", "api_key")
    if not api_key:
        logger.error("fal.ai API key not found in Secrets Manager")
        raise Exception("fal.ai API key not configured")

    logger.info(f"Generating image with fal.ai Flux ({model_id}): '{prompt[:50]}...'")
    
    # fal.ai REST API endpoint (sync proxy for queue)
    url = f"https://fal.run/{model_id}"
    
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json"
    }
    
    # Payload structured according to FLUX.2 Klein 9B Base OpenAPI schema
    payload = {
        "prompt": prompt,
        "image_size": image_size,
        "num_inference_steps": 28,  # OpenAPI default
        "guidance_scale": 5,        # OpenAPI default
        "sync_mode": False          # We'll fetch the URL returned for reliability
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code != 200:
                error_detail = response.text
                logger.error(f"fal.ai API error (Status {response.status_code}): {error_detail}")
                raise Exception(f"fal.ai API error: {error_detail}")
            
            data = response.json()
            images = data.get("images", [])
            
            if not images:
                raise Exception("fal.ai returned no images")
            
            image_url = images[0].get("url")
            if not image_url:
                raise Exception("fal.ai returned no image URL")
            
            # Fetch image bytes from URL
            img_response = await client.get(image_url)
            img_response.raise_for_status()
            
            image_bytes = img_response.content
            logger.info(f"Successfully generated image with fal.ai Flux ({len(image_bytes)} bytes)")
            return image_bytes

    except Exception as e:
        logger.error(f"Error during fal.ai Flux generation: {str(e)}", exc_info=True)
        raise e
