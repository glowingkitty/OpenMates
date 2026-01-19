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
    """
    requests: List[Dict[str, Any]] = Field(
        ...,
        description="Array of image generation request objects. Each object must contain 'prompt' and can include optional 'aspect_ratio'."
    )


class ImageGenerationResponse(BaseModel):
    """
    Response model for image generation skill.
    Returns task IDs and embed IDs for the generated images.
    """
    task_id: Optional[str] = Field(None, description="The ID of the Celery task (for single request).")
    embed_id: Optional[str] = Field(None, description="The ID of the result embed (for single request).")
    task_ids: Optional[List[str]] = Field(None, description="List of task IDs (for multiple requests).")
    embed_ids: Optional[List[str]] = Field(None, description="List of embed IDs (for multiple requests).")
    status: str = Field(default="processing", description="Initial status of the generation task(s).")
    error: Optional[str] = Field(None, description="Error message if generation failed to start.")


class GenerateSkill(BaseSkill):
    """
    Skill for generating images from text prompts.
    
    This skill is designed for long-running operations (> 5 seconds).
    It follows the asynchronous execution pattern with embed-based storage:
    1. Receives a request with a text prompt and optional parameters (aspect_ratio).
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
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute image generation requests.
        
        Args:
            requests: List of request objects, each containing at least a 'prompt' field.
            **kwargs: Additional context passed by the app (user_id, etc.)
            
        Returns:
            Dict containing task_id, embed_id, and status 'processing'.
            For multiple requests, returns arrays of task_ids and embed_ids.
        """
        if not self.celery_producer:
            logger.error(f"Celery producer not available in GenerateSkill (App: {self.app_id})")
            return {"error": "Image generation service temporarily unavailable"}

        # Extract user context for the task
        user_id = kwargs.get("user_id")
        
        # According to the multiple requests pattern, each request should be processed 
        # in parallel by spawning separate Celery tasks.
        results = []  # List of {task_id, embed_id} dicts
        
        for req in requests:
            prompt = req.get("prompt")
            if not prompt:
                logger.warning(f"Skipping image generation request: missing 'prompt' field. Req: {req}")
                continue
            
            # Generate embed_id here so we can return it immediately
            # The Celery task will create the embed with this ID
            embed_id = str(uuid.uuid4())
            
            # Prepare arguments for the Celery task
            # We include all relevant context for the task to process independently
            task_args = {
                "prompt": prompt,
                "aspect_ratio": req.get("aspect_ratio", "1:1"),
                "user_id": user_id,
                "chat_id": self._current_chat_id,
                "message_id": self._current_message_id,
                "app_id": self.app_id,
                "skill_id": self.skill_id,
                "full_model_reference": self.full_model_reference,
                "embed_id": embed_id  # Pass embed_id to the task
            }
            
            try:
                # Dispatch task to the app's dedicated queue (app_images)
                # execute_skill_via_celery follows the naming convention:
                # Task Name: apps.{app_id}.tasks.skill_{skill_id}
                # Queue Name: app_{app_id}
                task_id = await execute_skill_via_celery(
                    app_id=self.app_id,
                    skill_id=self.skill_id,
                    arguments=task_args,
                    celery_producer=self.celery_producer
                )
                results.append({
                    "task_id": task_id,
                    "embed_id": embed_id
                })
                logger.info(f"Dispatched image generation task {task_id} (embed: {embed_id}) for prompt: '{prompt[:50]}...'")
                
            except Exception as e:
                logger.error(f"Failed to dispatch image generation task: {e}", exc_info=True)
                # If we have some successful tasks, we continue. Otherwise, return error.
                if not results:
                    return {"error": f"Failed to start image generation: {str(e)}"}
        
        if not results:
            return {"error": "No valid prompts provided"}
            
        # Unified response format for long-running skills
        if len(results) == 1:
            return {
                "task_id": results[0]["task_id"],
                "embed_id": results[0]["embed_id"],
                "status": "processing"
            }
        else:
            return {
                "task_ids": [r["task_id"] for r in results],
                "embed_ids": [r["embed_id"] for r in results],
                "status": "processing"
            }
