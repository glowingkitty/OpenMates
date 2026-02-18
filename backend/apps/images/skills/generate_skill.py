# backend/apps/images/skills/generate_skill.py
#
# Image generation skill implementation.
# This skill handles text-to-image generation requests by dispatching them
# as asynchronous Celery tasks to the images app's worker container.
#
# Architecture:
# - Each request dispatches a Celery task that creates an embed with the generated image
# - The embed_id is included in the response so clients can poll for status and download
# - Download via GET /v1/embeds/{embed_id}/file?format=preview|full|original
# - See docs/architecture/apps/images.md for full architecture details
#
# Output filetype routing:
#   output_filetype="png"|"jpg"  → existing raster pipeline (Google Gemini / fal.ai FLUX)
#   output_filetype="svg"        → Recraft V4 Vector pipeline
#     quality="default"          → recraftv4_vector     ($0.08/image, 80 credits)
#     quality="max"              → recraftv4_pro_vector ($0.30/image, 300 credits)

import logging
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from backend.apps.base_skill import BaseSkill
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery

logger = logging.getLogger(__name__)


class ImageGenerationRequest(BaseModel):
    """
    Request model for image generation skill.
    Supports multiple generation requests in a single call.

    Each item in 'requests' may include:
      - prompt         (required): Text description of the image.
      - aspect_ratio   (optional): "1:1", "16:9", etc. Defaults to "1:1".
      - output_filetype (optional): "png", "jpg", or "svg". Defaults to "png".
                        Use "svg" to generate scalable vector graphics via Recraft V4.
      - quality        (optional): "default" or "max". Only relevant when
                        output_filetype="svg". Selects recraftv4_vector (default)
                        or recraftv4_pro_vector (max). Defaults to "default".
    """

    requests: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Array of image generation request objects. Each object must contain 'prompt' "
            "and can include optional 'aspect_ratio', 'output_filetype' (png|jpg|svg), "
            "and 'quality' (default|max, only relevant for svg)."
        ),
    )


class ImageGenerationResponse(BaseModel):
    """
    Response model for image generation skill.
    Returns task IDs and embed IDs for the generated images.
    """

    task_id: Optional[str] = Field(
        None, description="The ID of the Celery task (for single request)."
    )
    embed_id: Optional[str] = Field(
        None, description="The ID of the result embed (for single request)."
    )
    task_ids: Optional[List[str]] = Field(
        None, description="List of task IDs (for multiple requests)."
    )
    embed_ids: Optional[List[str]] = Field(
        None, description="List of embed IDs (for multiple requests)."
    )
    status: str = Field(
        default="processing", description="Initial status of the generation task(s)."
    )
    error: Optional[str] = Field(
        None, description="Error message if generation failed to start."
    )


class GenerateSkill(BaseSkill):
    """
    Skill for generating images from text prompts.

    Supports two output modes:
    - Raster (png/jpg): routes to Google Gemini (generate) or fal.ai FLUX (generate_draft)
    - Vector (svg):     routes to Recraft V4 Vector API regardless of skill variant
                        quality="default" → recraftv4_vector     (80 credits)
                        quality="max"     → recraftv4_pro_vector (300 credits)

    This skill is designed for long-running operations (> 5 seconds).
    It follows the asynchronous execution pattern with embed-based storage:
    1. Receives a request with a text prompt and optional parameters.
    2. Generates an embed_id for the result (to be created by the Celery task).
    3. Dispatches a Celery task to the app's dedicated worker queue (app_images).
    4. Returns task_id and embed_id immediately to the caller.
    5. The caller polls the task status endpoint for completion.
    6. Once complete, the caller downloads via /v1/embeds/{embed_id}/file endpoint.

    Supports multiple generation requests in a single call, dispatching each as
    a separate parallel Celery task.
    """

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Execute image generation requests.

        Args:
            requests: List of request objects, each containing at minimum a 'prompt' field.
                      Optional per-request fields:
                        - aspect_ratio   ("1:1", "16:9", etc.)
                        - output_filetype ("png", "jpg", "svg")
                        - quality        ("default", "max") — SVG only
            **kwargs: Additional context passed by the app (user_id, etc.)

        Returns:
            Dict containing task_id, embed_id, and status 'processing'.
            For multiple requests, returns arrays of task_ids and embed_ids.
        """
        if not self.celery_producer:
            logger.error(
                f"Celery producer not available in GenerateSkill (App: {self.app_id})"
            )
            return {"error": "Image generation service temporarily unavailable"}

        # Extract user context for the task
        user_id = kwargs.get("user_id")

        # Accept placeholder embed_ids from main_processor context.
        # When the main_processor creates placeholder embeds before skill execution,
        # it passes the embed_ids so the Celery task can UPDATE the existing placeholder
        # instead of creating a new embed. This enables the in-place transition from
        # "processing" -> "finished" in the frontend.
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids", [])

        # According to the multiple requests pattern, each request should be processed
        # in parallel by spawning separate Celery tasks.
        results: List[Dict[str, Any]] = []

        for idx, req in enumerate(requests):
            prompt = req.get("prompt")
            if not prompt:
                logger.warning(
                    f"Skipping image generation request: missing 'prompt' field. Req: {req}"
                )
                continue

            # Use placeholder embed_id if available (from main_processor),
            # otherwise generate a new one (backward compatibility / standalone usage).
            if idx < len(placeholder_embed_ids) and placeholder_embed_ids[idx]:
                embed_id = placeholder_embed_ids[idx]
                logger.info(
                    f"Using placeholder embed_id from main_processor: {embed_id}"
                )
            else:
                embed_id = str(uuid.uuid4())
                logger.info(
                    f"No placeholder embed_id for request {idx}, generating new: {embed_id}"
                )

            # Normalise output_filetype: accept "png", "jpg", "svg" (case-insensitive).
            # Default to "png" for backward compatibility.
            output_filetype = str(req.get("output_filetype", "png")).lower()
            if output_filetype not in ("png", "jpg", "svg"):
                logger.warning(
                    f"Unknown output_filetype '{output_filetype}', falling back to 'png'"
                )
                output_filetype = "png"

            # quality only applies to SVG output (selects Recraft model tier):
            #   "default" → recraftv4_vector     (80 credits,  $0.08/image)
            #   "max"     → recraftv4_pro_vector  (300 credits, $0.30/image)
            quality = str(req.get("quality", "default")).lower()
            if quality not in ("default", "max"):
                logger.warning(
                    f"Unknown quality '{quality}', falling back to 'default'"
                )
                quality = "default"

            # Prepare arguments for the Celery task.
            # We include all relevant context for the task to process independently.
            task_args = {
                "prompt": prompt,
                "aspect_ratio": req.get("aspect_ratio", "1:1"),
                "output_filetype": output_filetype,
                "quality": quality,
                "user_id": user_id,
                "chat_id": self._current_chat_id,
                "message_id": self._current_message_id,
                "app_id": self.app_id,
                "skill_id": self.skill_id,
                "full_model_reference": self.full_model_reference,
                "embed_id": embed_id,
            }

            try:
                # Dispatch task to the app's dedicated queue (app_images).
                # execute_skill_via_celery follows the naming convention:
                # Task Name: apps.{app_id}.tasks.skill_{skill_id}
                # Queue Name: app_{app_id}
                task_id = await execute_skill_via_celery(
                    app_id=self.app_id,
                    skill_id=self.skill_id,
                    arguments=task_args,
                    celery_producer=self.celery_producer,
                )
                results.append({"task_id": task_id, "embed_id": embed_id})
                logger.info(
                    f"Dispatched image generation task {task_id} "
                    f"(embed: {embed_id}, filetype: {output_filetype}, quality: {quality}) "
                    f"for prompt: '{prompt[:50]}...'"
                )

            except Exception as e:
                logger.error(
                    f"Failed to dispatch image generation task: {e}", exc_info=True
                )
                # If we have some successful tasks, continue. Otherwise, return error.
                if not results:
                    return {"error": f"Failed to start image generation: {str(e)}"}

        if not results:
            return {"error": "No valid prompts provided"}

        # Unified response format for long-running skills
        if len(results) == 1:
            return {
                "task_id": results[0]["task_id"],
                "embed_id": results[0]["embed_id"],
                "status": "processing",
            }
        else:
            return {
                "task_ids": [r["task_id"] for r in results],
                "embed_ids": [r["embed_id"] for r in results],
                "status": "processing",
            }
