# backend/core/api/app/routes/handlers/websocket_handlers/cancel_skill_handler.py
# Handles WebSocket requests to cancel an individual skill execution.
#
# SKILL-LEVEL CANCELLATION:
# Unlike cancel_ai_task which revokes the entire Celery task (stopping the whole AI response),
# this handler only cancels a specific skill execution. The main AI processing continues
# and will receive a "cancelled" result for this skill, allowing it to proceed without
# that skill's data.
#
# This is useful when:
# - A skill is taking too long and the user wants to proceed without its results
# - The user realizes they don't need the skill output
# - The user wants to retry with different parameters

import logging
from typing import Dict, Any
from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.apps.ai.processing.skill_executor import cancel_skill_task

logger = logging.getLogger(__name__)


async def handle_cancel_skill(
    websocket: WebSocket,
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    cache_service: CacheService
):
    """
    Handles a request to cancel an individual skill execution.
    
    This cancels only the specific skill identified by skill_task_id, NOT the entire
    AI response. The main processor will continue and receive a "cancelled" result
    for this skill.
    
    Payload is expected to contain:
    {
        "skill_task_id": "unique_skill_task_id_to_cancel",
        "embed_id": "optional_embed_id_for_logging"  // Optional, for better logging
    }
    
    Response:
    {
        "type": "skill_cancel_requested",
        "payload": {
            "skill_task_id": "...",
            "status": "cancellation_requested"
        }
    }
    """
    skill_task_id = payload.get("skill_task_id")
    embed_id = payload.get("embed_id", "unknown")  # Optional, for logging
    
    log_prefix = f"[CancelSkill][User: {user_id[:6]}][Device: {device_fingerprint_hash[:6]}]"

    # Validate required field
    if not skill_task_id:
        logger.warning(f"{log_prefix} 'skill_task_id' not provided in cancel_skill payload: {payload}")
        await manager.send_personal_message(
            message={
                "type": "error", 
                "payload": {
                    "message": "Skill task ID is required for cancellation.", 
                    "details": "missing_skill_task_id"
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"{log_prefix} Received request to cancel skill_task_id: {skill_task_id} (embed_id: {embed_id})")

    try:
        # Mark the skill as cancelled in Redis
        # The skill executor checks this flag before/during execution
        success = await cancel_skill_task(cache_service, skill_task_id)
        
        if success:
            logger.info(f"{log_prefix} Skill cancellation requested for skill_task_id: {skill_task_id}")
            
            await manager.send_personal_message(
                message={
                    "type": "skill_cancel_requested", 
                    "payload": {
                        "skill_task_id": skill_task_id, 
                        "embed_id": embed_id,
                        "status": "cancellation_requested"
                    }
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
        else:
            logger.warning(f"{log_prefix} Failed to mark skill as cancelled: skill_task_id={skill_task_id}")
            await manager.send_personal_message(
                message={
                    "type": "error", 
                    "payload": {
                        "message": f"Failed to cancel skill {skill_task_id}.", 
                        "details": "cancellation_failed"
                    }
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            
    except Exception as e:
        logger.error(f"{log_prefix} Error cancelling skill_task_id {skill_task_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={
                "type": "error", 
                "payload": {
                    "message": f"Failed to send cancellation for skill {skill_task_id}.", 
                    "details": str(e)
                }
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )

