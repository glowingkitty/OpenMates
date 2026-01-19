# backend/core/api/app/routes/tasks_api.py
#
# External API endpoints for polling the status of long-running tasks.
# This router provides a unified endpoint for tracking asynchronous skill execution.
#
# Architecture:
# - Long-running skills (like image generation) return a task_id and embed_id
# - Clients poll this endpoint to check task status
# - When completed, the result includes embed_id and file metadata
# - Files are downloaded via GET /v1/embeds/{embed_id}/file endpoint
# - See docs/architecture/apps/images.md for full flow

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from celery.result import AsyncResult

from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.utils.api_key_auth import ApiKeyAuth
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tasks", tags=["Tasks"])


class TaskStatusResponse(BaseModel):
    """
    Response model for task status polling.
    
    For tasks that generate files (like images), the result will include:
    - embed_id: The ID of the embed containing the file references
    - files: Metadata about available file formats
    
    Use GET /v1/embeds/{embed_id}/file?format=... to download files.
    """
    task_id: str = Field(..., description="The unique ID of the asynchronous task")
    status: str = Field(..., description="Current status of the task (pending, processing, completed, failed)")
    result: Optional[Any] = Field(None, description="The result of the task (only present when status is 'completed'). For image tasks, includes embed_id and file metadata.")
    error: Optional[str] = Field(None, description="Error details (only present when status is 'failed')")

@router.get("/{task_id}", response_model=TaskStatusResponse)
@limiter.limit("60/minute")
async def get_task_status(
    task_id: str,
    request: Request,
    user_info: Dict[str, Any] = ApiKeyAuth
):
    """
    Poll for the status and result of a long-running task.
    
    Requires API key authentication.
    Rate limited to 60 requests per minute per API key.
    
    This endpoint is used for tasks that return a task ID immediately, 
    such as image generation or video processing.
    """
    try:
        # Get task result using Celery's AsyncResult
        # We pass the celery_app instance to ensure it uses the correct result backend
        result = AsyncResult(task_id, app=celery_app)
        
        # Determine status string
        # Celery states: PENDING, STARTED, SUCCESS, FAILURE, REVOKED, RETRY
        # We map these to simpler strings for the public API
        raw_status = result.status
        if raw_status == 'SUCCESS':
            status_str = 'completed'
        elif raw_status == 'FAILURE':
            status_str = 'failed'
        elif raw_status == 'REVOKED':
            status_str = 'failed'
        elif raw_status == 'PENDING':
            status_str = 'pending'
        else:
            status_str = 'processing'
            
        response = TaskStatusResponse(
            task_id=task_id,
            status=status_str
        )
        
        # If task is completed, include the result
        if raw_status == 'SUCCESS':
            response.result = result.result
        elif raw_status == 'FAILURE' or raw_status == 'REVOKED':
            # For failures, the 'result' property often contains the exception object
            # or a string representation of the error
            response.error = str(result.result) if result.result else "Unknown error occurred during task execution"
        
        return response
        
    except Exception as e:
        logger.error(f"Error checking status for task {task_id} (User: {user_info.get('user_id')}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while checking task status")

# Note: The old download endpoint (/v1/tasks/{task_id}/download) has been removed.
# Files are now downloaded via GET /v1/embeds/{embed_id}/file endpoint.
# See docs/architecture/apps/images.md for the updated architecture.
