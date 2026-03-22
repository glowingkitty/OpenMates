# backend/apps/images/skills/vectorize_skill.py
#
# Image vectorization skill implementation.
# Converts a user-uploaded raster image (PNG/JPG/WEBP) to a scalable SVG vector
# using the Recraft /v1/images/vectorize API endpoint.
#
# Architecture:
# - User provides a source image via embed_ref (the original filename of an uploaded image)
# - The skill resolves the embed_ref → internal embed_id via file_path_index
# - Dispatches a Celery task to the images worker queue (app_images)
# - The task decrypts the source image, calls Recraft vectorize, and stores the SVG result
# - The SVG result is delivered as a new embed via WebSocket (same flow as generate)
#
# Cost: $0.01 API cost → 15 credits charged (50% margin over $0.01 break-even)
# Input: PNG, JPG, or WEBP (max 5 MB, max 16 MP, max 4096px dimension)
# Output: SVG vector image

import logging
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from backend.apps.base_skill import BaseSkill
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery

logger = logging.getLogger(__name__)


class VectorizeRequest(BaseModel):
    """
    Request model for image vectorization skill.
    Accepts a source image embed_ref to convert from raster to SVG.
    """

    source_image: str = Field(
        ...,
        description=(
            "The original filename (embed_ref) of the uploaded raster image to vectorize. "
            "Must be a PNG, JPG, or WEBP image. Use the exact embed_ref value from the "
            "toon block in the user's conversation."
        ),
    )


class VectorizeResponse(BaseModel):
    """
    Response model for image vectorization skill.
    Returns task ID and embed ID for the vectorized SVG.
    """

    task_id: Optional[str] = Field(
        None, description="The ID of the Celery task."
    )
    embed_id: Optional[str] = Field(
        None, description="The ID of the result embed containing the SVG."
    )
    status: str = Field(
        default="processing",
        description="Initial status of the vectorization task.",
    )
    error: Optional[str] = Field(
        None, description="Error message if vectorization failed to start."
    )


class VectorizeSkill(BaseSkill):
    """
    Skill for converting raster images (PNG/JPG/WEBP) to scalable SVG vectors.

    Uses the Recraft /v1/images/vectorize API endpoint. This is a separate skill
    from images.generate to keep routing logic clean and billing transparent:
    - Different input signature (requires an uploaded image, no text prompt)
    - Different Recraft endpoint (POST /images/vectorize, not /images/generations)
    - Different pricing ($0.01 API cost → 15 credits, vs generate's $0.04–$0.30)

    This skill follows the same async execution pattern as GenerateSkill:
    1. Receives a request with a source image embed_ref
    2. Resolves the embed_ref to an internal embed_id via file_path_index
    3. Generates an embed_id for the SVG result
    4. Dispatches a Celery task to the app_images queue
    5. Returns task_id and embed_id immediately
    6. The task decrypts the source, calls Recraft, and delivers the SVG via WebSocket
    """

    async def execute(
        self,
        source_image: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Execute image vectorization.

        Args:
            source_image: The embed_ref (original filename) of the raster image to vectorize.
                          Resolved to an internal embed_id via file_path_index.
            **kwargs: Additional context passed by the app (user_id, file_path_index, etc.)

        Returns:
            Dict containing task_id, embed_id, and status 'processing'.
        """
        if not self.celery_producer:
            logger.error(
                f"Celery producer not available in VectorizeSkill (App: {self.app_id})"
            )
            return {"error": "Vectorization service temporarily unavailable"}

        user_id = kwargs.get("user_id")
        user_vault_key_id = kwargs.get("user_vault_key_id")
        file_path_index: Dict[str, str] = kwargs.get("file_path_index") or {}
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids", [])

        if not source_image:
            logger.error("VectorizeSkill: source_image is required")
            return {"error": "source_image is required — provide the filename of the image to vectorize"}

        # Resolve the embed_ref (filename) → internal embed_id
        source_embed_id = file_path_index.get(source_image)
        if not source_embed_id:
            logger.warning(
                f"VectorizeSkill: source_image '{source_image}' not found in file_path_index "
                f"(available keys: {list(file_path_index.keys())})"
            )
            return {
                "error": (
                    f"Source image '{source_image}' not found in conversation. "
                    "Make sure the image has been uploaded in this conversation."
                )
            }

        logger.info(
            f"VectorizeSkill: Resolved source_image '{source_image}' → embed_id {source_embed_id}"
        )

        # Use placeholder embed_id if available (from main_processor)
        if placeholder_embed_ids and placeholder_embed_ids[0]:
            embed_id = placeholder_embed_ids[0]
            logger.info(f"VectorizeSkill: Using placeholder embed_id: {embed_id}")
        else:
            embed_id = str(uuid.uuid4())
            logger.info(f"VectorizeSkill: Generated new embed_id: {embed_id}")

        # Prepare Celery task arguments
        task_args = {
            "user_id": user_id,
            "chat_id": self._current_chat_id,
            "message_id": self._current_message_id,
            "app_id": self.app_id,
            "skill_id": self.skill_id,
            "embed_id": embed_id,
            "source_image_embed_id": source_embed_id,
            "user_vault_key_id": user_vault_key_id,
        }

        try:
            task_id = await execute_skill_via_celery(
                app_id=self.app_id,
                skill_id=self.skill_id,
                arguments=task_args,
                celery_producer=self.celery_producer,
            )

            logger.info(
                f"VectorizeSkill: Dispatched vectorize task {task_id} "
                f"(embed: {embed_id}, source: {source_image})"
            )

            return {
                "task_id": task_id,
                "embed_id": embed_id,
                "status": "processing",
            }

        except Exception as e:
            logger.error(
                f"VectorizeSkill: Failed to dispatch vectorize task: {e}",
                exc_info=True,
            )
            return {"error": f"Failed to start vectorization: {str(e)}"}
