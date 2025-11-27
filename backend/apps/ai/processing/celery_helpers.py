# backend/apps/ai/processing/celery_helpers.py
#
# Celery task helpers for long-running skill execution.
# Handles task dispatch to app-specific Celery worker containers and status polling.

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


async def execute_skill_via_celery(
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    celery_producer: Any  # Celery instance
) -> str:
    """
    Execute a skill via Celery task for long-running operations.
    
    This function creates a Celery task for skill execution and returns a task ID.
    The caller should poll for task completion using the task ID.
    
    According to app_skills.md architecture, long-running tasks are executed in
    app-specific Celery worker containers. Each app has its own queue (app_{app_id}).
    
    Args:
        app_id: The app ID that owns the skill
        skill_id: The skill ID to execute
        arguments: The arguments to pass to the skill
        celery_producer: Celery instance for task creation
    
    Returns:
        Task ID string for polling task status
    
    Raises:
        ValueError: If celery_producer is None or invalid
        Exception: If task dispatch fails
    """
    if not celery_producer:
        error_msg = f"Cannot execute skill '{app_id}.{skill_id}' via Celery: celery_producer is None"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    try:
        # Task name follows the pattern: apps.{app_id}.tasks.skill_{skill_id}
        # This matches the pattern used in ask_skill: "apps.ai.tasks.skill_ask"
        task_name = f"apps.{app_id}.tasks.skill_{skill_id}"
        
        # Queue name follows the pattern: app_{app_id}
        # This routes the task to the app's dedicated Celery worker container
        queue_name = f"app_{app_id}"
        
        # Dispatch the task to the app's queue
        # The task will be executed in the app's Celery worker container
        task_signature = celery_producer.send_task(
            name=task_name,
            kwargs={"arguments": arguments},
            queue=queue_name
        )
        
        task_id = task_signature.id
        logger.info(
            f"Dispatched Celery task '{task_name}' for skill '{app_id}.{skill_id}' "
            f"to queue '{queue_name}' with task ID: {task_id}"
        )
        
        return task_id
        
    except Exception as e:
        error_msg = f"Failed to dispatch Celery task for skill '{app_id}.{skill_id}': {e}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg) from e


async def get_celery_task_status(
    task_id: str,
    celery_producer: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Get the status of a Celery task.
    
    Queries the Celery result backend to get the current status, result, and error
    information for a task. This is used for polling long-running skill executions.
    
    Args:
        task_id: The task ID returned from execute_skill_via_celery
        celery_producer: Optional Celery instance (needed to access result backend)
    
    Returns:
        Dict with task status information:
        {
            "status": "pending|processing|completed|failed|revoked",
            "result": {...},  # Only if completed
            "error": {...}    # Only if failed
        }
    """
    try:
        # If no celery_producer provided, we can't check status
        # In this case, we'd need to create a minimal Celery instance just for result checking
        # For now, we'll require it to be passed
        if not celery_producer:
            logger.warning(f"Cannot check Celery task status for '{task_id}': celery_producer not provided")
            return {
                "status": "unknown",
                "result": None,
                "error": "Celery producer not available for status check"
            }
        
        # Get task result using Celery's AsyncResult
        from celery.result import AsyncResult
        task_result = AsyncResult(task_id, app=celery_producer)
        
        # Get task state
        task_state = task_result.state
        
        # Map Celery states to our status format
        status_map = {
            "PENDING": "pending",
            "STARTED": "processing",
            "SUCCESS": "completed",
            "FAILURE": "failed",
            "REVOKED": "revoked",
            "RETRY": "processing",
            "REJECTED": "failed"
        }
        status = status_map.get(task_state, "unknown")
        
        result_data = None
        error_data = None
        
        if task_state == "SUCCESS":
            # Task completed successfully
            try:
                result_data = task_result.result
                if isinstance(result_data, Exception):
                    # Sometimes exceptions are stored as results
                    error_data = {
                        "type": type(result_data).__name__,
                        "message": str(result_data)
                    }
                    status = "failed"
                    result_data = None
            except Exception as e:
                logger.warning(f"Error retrieving result for task '{task_id}': {e}")
                result_data = None
        
        elif task_state == "FAILURE":
            # Task failed
            try:
                error_info = task_result.info
                if isinstance(error_info, Exception):
                    error_data = {
                        "type": type(error_info).__name__,
                        "message": str(error_info)
                    }
                elif isinstance(error_info, dict):
                    error_data = error_info
                else:
                    error_data = {"message": str(error_info)}
            except Exception as e:
                logger.warning(f"Error retrieving error info for task '{task_id}': {e}")
                error_data = {"message": "Error information not available"}
        
        logger.debug(f"Task '{task_id}' status: {status} (Celery state: {task_state})")
        
        return {
            "status": status,
            "result": result_data,
            "error": error_data
        }
        
    except Exception as e:
        logger.error(f"Error checking Celery task status for '{task_id}': {e}", exc_info=True)
        return {
            "status": "unknown",
            "result": None,
            "error": {"message": f"Error checking task status: {str(e)}"}
        }

