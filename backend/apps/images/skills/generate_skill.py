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
#   output_filetype="svg"        → Recraft V4 Vector pipeline
#     quality="default"          → recraftv4_vector     ($0.08/image, 100 credits)
#     quality="max"              → recraftv4_pro_vector ($0.30/image, 300 credits)
#   output_filetype="png"|"jpg" with recraft model → Recraft V4 Raster pipeline
#     quality="default"          → recraftv4     ($0.04/image,  50 credits, 1024×1024)
#     quality="max"              → recraftv4_pro ($0.25/image, 250 credits, 2048×2048)
#   output_filetype="png"|"jpg" with google model  → Google Gemini (default)
#   output_filetype="png"|"jpg" with bfl/flux model → fal.ai FLUX

import logging
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from backend.apps.base_skill import BaseSkill
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery

logger = logging.getLogger(__name__)


class ImageGenerationRequestItem(BaseModel):
    """A single image generation request."""

    prompt: str = Field(description="Text description of the image to generate.")
    aspect_ratio: str = Field(
        default="1:1",
        description="Aspect ratio of the generated image (e.g. '1:1', '16:9', '9:16'). Defaults to '1:1'.",
    )
    output_filetype: str = Field(
        default="png",
        description="Output file type: 'png', 'jpg', or 'svg'. Use 'svg' for scalable vector graphics via Recraft V4.",
    )
    quality: str = Field(
        default="default",
        description="Quality/model tier: 'default' or 'max'. Only relevant for svg and recraft raster models.",
    )
    reference_images: Optional[List[str]] = Field(
        default=None,
        description="List of embed_ref filenames to use as visual references (enables image-to-image editing).",
    )


class ImageGenerationRequest(BaseModel):
    """
    Request model for image generation skill.
    Supports multiple generation requests in a single call.
    """

    requests: List[ImageGenerationRequestItem] = Field(
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

    Supports three output modes:
    - Vector (svg):              routes to Recraft V4 Vector API
                                 quality="default" → recraftv4_vector     (100 credits)
                                 quality="max"     → recraftv4_pro_vector (300 credits)
    - Raster (png/jpg) + recraft model: routes to Recraft V4 Raster API
                                 quality="default" → recraftv4     ( 50 credits, 1024×1024)
                                 quality="max"     → recraftv4_pro (250 credits, 2048×2048)
    - Raster (png/jpg) + other model: routes to Google Gemini (default) or fal.ai FLUX

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
                        - aspect_ratio      ("1:1", "16:9", etc.)
                        - output_filetype   ("png", "jpg", "svg")
                        - quality           ("default", "max") — SVG only
                        - reference_images  (list of embed_ref filenames for image-to-image)
            **kwargs: Additional context passed by the app (user_id, file_path_index, etc.)

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
        # vault key ID needed by the Celery task to decrypt reference image embeds
        user_vault_key_id = kwargs.get("user_vault_key_id")

        # file_path_index maps original filenames (embed_refs) → internal embed_id UUIDs.
        # It is built during message history resolution and injected by main_processor.py
        # so the LLM's human-readable filenames can be resolved server-side to internal IDs.
        file_path_index: Dict[str, str] = kwargs.get("file_path_index") or {}

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
            #   "default" → recraftv4_vector     (100 credits, $0.08/image API cost)
            #   "max"     → recraftv4_pro_vector  (300 credits, $0.30/image API cost)
            quality = str(req.get("quality", "default")).lower()
            if quality not in ("default", "max"):
                logger.warning(
                    f"Unknown quality '{quality}', falling back to 'default'"
                )
                quality = "default"

            # Resolve reference_images (embed_refs / filenames) → internal embed_id UUIDs.
            # The LLM provides human-readable filenames; we look them up in file_path_index
            # to get the internal UUIDs needed by the Celery task for Redis cache lookup.
            # We pass embed_ids (not bytes) to keep the Celery message payload small.
            reference_image_embed_ids: List[str] = []
            raw_reference_images = req.get("reference_images") or []
            for ref_filename in raw_reference_images:
                embed_id_ref = file_path_index.get(ref_filename)
                if embed_id_ref:
                    reference_image_embed_ids.append(embed_id_ref)
                    logger.info(
                        f"Resolved reference image '{ref_filename}' → embed_id {embed_id_ref}"
                    )
                else:
                    logger.warning(
                        f"Reference image '{ref_filename}' not found in file_path_index "
                        f"(available keys: {list(file_path_index.keys())}) — skipping"
                    )

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
                # Reference image embed IDs for image-to-image generation.
                # The Celery task fetches, decrypts, and passes these to the provider.
                "reference_image_embed_ids": reference_image_embed_ids,
                # Vault key ID needed by the Celery task to decrypt reference image embeds
                # (same key used by view_skill.py for embed content decryption).
                "user_vault_key_id": user_vault_key_id,
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
