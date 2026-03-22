# backend/shared/providers/fal/flux.py
#
# fal.ai Flux API client for image generation using httpx.
#
# Two endpoint modes:
#   TEXT-TO-IMAGE  → fal-ai/flux-2/klein/9b/base
#     Used when no reference images are provided.
#     Accepts: prompt, image_size
#     Pricing: $0.011/MP output
#
#   IMAGE-TO-IMAGE → fal-ai/flux-2/klein/4b/base/edit
#     Used automatically when reference_image_bytes_list is provided.
#     Accepts: prompt, image_urls (base64 data URIs or public URLs), image_size
#     Pricing: $0.009/MP for BOTH input and output images.
#     Input images are resized to 1MP by fal.ai automatically.
#     Max 4 reference images per request.

import base64
import logging
from typing import List, Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Image-to-image edit endpoint (4B model, supports reference images)
FAL_FLUX_EDIT_MODEL = "fal-ai/flux-2/klein/4b/base/edit"


async def generate_image_fal_flux(
    prompt: str,
    secrets_manager: SecretsManager,
    model_id: str = "fal-ai/flux-2/klein/9b/base",
    image_size: str = "landscape_4_3",
    reference_image_bytes_list: Optional[List[bytes]] = None,
    reference_image_mime_types: Optional[List[str]] = None,
) -> bytes:
    """
    Generate an image using fal.ai Flux API via HTTP REST.

    When reference images are provided, automatically switches to the image-to-image
    edit endpoint (fal-ai/flux-2/klein/4b/base/edit) regardless of the model_id
    parameter. This endpoint accepts 1-4 reference images alongside the text prompt.

    Args:
        prompt: The text prompt for generation
        secrets_manager: For API key retrieval
        model_id: Specific model path on fal.ai (used for text-to-image only;
                  image-to-image always uses FAL_FLUX_EDIT_MODEL)
        image_size: Aspect ratio / size preset (e.g., landscape_4_3, square_hd).
                    Ignored for image-to-image (uses input image size by default).
        reference_image_bytes_list: Optional list of raw image bytes for reference.
                                     When provided, switches to image-to-image mode.
                                     Maximum 4 images; each is resized to 1MP by fal.ai.
        reference_image_mime_types: Optional MIME types for each reference image
                                     (e.g., ["image/jpeg", "image/png"]).
                                     Defaults to "image/webp" if not provided.

    Returns:
        Raw image bytes (PNG/JPEG/WEBP)
    """
    # Fetch API key
    api_key = await secrets_manager.get_secret("kv/data/providers/fal", "api_key")
    if not api_key:
        logger.error("fal.ai API key not found in Secrets Manager")
        raise Exception("fal.ai API key not configured")

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }

    has_reference_images = bool(reference_image_bytes_list)

    if has_reference_images:
        return await _generate_with_reference_images(
            prompt=prompt,
            reference_image_bytes_list=reference_image_bytes_list,  # type: ignore[arg-type]
            reference_image_mime_types=reference_image_mime_types,
            headers=headers,
        )
    else:
        return await _generate_text_to_image(
            prompt=prompt,
            model_id=model_id,
            image_size=image_size,
            headers=headers,
        )


async def _generate_text_to_image(
    prompt: str,
    model_id: str,
    image_size: str,
    headers: dict,
) -> bytes:
    """
    Text-to-image generation using the specified FLUX model.

    Uses the standard text-to-image endpoint (e.g. fal-ai/flux-2/klein/9b/base).
    """
    url = f"https://fal.run/{model_id}"

    logger.info(f"Generating text-to-image with fal.ai Flux ({model_id}): '{prompt[:50]}...'")

    # Payload structured according to FLUX.2 9B Base OpenAPI schema
    payload = {
        "prompt": prompt,
        "image_size": image_size,
        "num_inference_steps": 28,  # OpenAPI default
        "guidance_scale": 5,        # OpenAPI default
        "sync_mode": False,         # We'll fetch the URL returned for reliability
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
            logger.info(
                f"Successfully generated text-to-image with fal.ai Flux "
                f"({len(image_bytes)} bytes)"
            )
            return image_bytes

    except Exception as e:
        logger.error(f"Error during fal.ai Flux text-to-image generation: {str(e)}", exc_info=True)
        raise e


async def _generate_with_reference_images(
    prompt: str,
    reference_image_bytes_list: List[bytes],
    reference_image_mime_types: Optional[List[str]],
    headers: dict,
) -> bytes:
    """
    Image-to-image generation using the FLUX.2 [klein] 4B edit endpoint.

    Converts reference image bytes to base64 data URIs and passes them as
    image_urls to the edit endpoint. fal.ai automatically resizes each input
    image to 1MP for pricing purposes.

    API: fal-ai/flux-2/klein/4b/base/edit
    Pricing: $0.009/MP for each input image + $0.009/MP for output image.
    """
    url = f"https://fal.run/{FAL_FLUX_EDIT_MODEL}"

    # Limit to 4 reference images (fal.ai API maximum)
    images_to_use = reference_image_bytes_list[:4]
    mime_types_to_use = (reference_image_mime_types or [])[:4]

    logger.info(
        f"Generating image-to-image with fal.ai Flux edit ({FAL_FLUX_EDIT_MODEL}), "
        f"{len(images_to_use)} reference image(s): '{prompt[:50]}...'"
    )

    # Convert bytes to base64 data URIs for fal.ai
    image_urls = []
    for idx, img_bytes in enumerate(images_to_use):
        # Determine MIME type: use provided type, fallback to webp (our standard storage format)
        if idx < len(mime_types_to_use) and mime_types_to_use[idx]:
            mime_type = mime_types_to_use[idx]
        else:
            mime_type = "image/webp"

        b64_data = base64.b64encode(img_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_data}"
        image_urls.append(data_uri)

    # Payload for the image-to-image edit endpoint
    # Note: image_size is omitted — the edit endpoint uses the input image size by default,
    # which produces the most natural results for reference-guided generation.
    payload = {
        "prompt": prompt,
        "image_urls": image_urls,
        "num_inference_steps": 28,  # Default for quality-speed balance
        "guidance_scale": 5,
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            # Image-to-image can take longer due to processing reference images
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                error_detail = response.text
                logger.error(
                    f"fal.ai edit API error (Status {response.status_code}): {error_detail}"
                )
                raise Exception(f"fal.ai edit API error: {error_detail}")

            data = response.json()
            images = data.get("images", [])

            if not images:
                raise Exception("fal.ai edit endpoint returned no images")

            image_url = images[0].get("url")
            if not image_url:
                raise Exception("fal.ai edit endpoint returned no image URL")

            # Fetch image bytes from fal.ai CDN URL
            img_response = await client.get(image_url)
            img_response.raise_for_status()

            image_bytes = img_response.content
            logger.info(
                f"Successfully generated image-to-image with fal.ai Flux edit "
                f"({len(image_bytes)} bytes, {len(images_to_use)} reference image(s))"
            )
            return image_bytes

    except Exception as e:
        logger.error(
            f"Error during fal.ai Flux image-to-image generation: {str(e)}", exc_info=True
        )
        raise e
