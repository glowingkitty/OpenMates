# backend/apps/ai/tasks/rate_limit_followup_task.py
#
# Celery task for processing completed rate-limited skill executions and sending followup messages.
# This task is automatically chained after rate-limited skill tasks complete.

import logging
import asyncio
from typing import Dict, Any, Optional

from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.encryption import EncryptionService
from backend.core.api.app.services.embed_service import EmbedService

logger = logging.getLogger(__name__)


async def _async_process_rate_limit_followup(
    skill_result: Any,  # Result from the skill task (first argument from chain)
    app_id: str,
    skill_id: str,
    chat_id: Optional[str],
    message_id: Optional[str],
    user_id: Optional[str],
    user_id_hash: Optional[str]
) -> Dict[str, Any]:
    """
    Process completed rate-limited skill execution and send followup message.
    
    This function:
    1. Receives skill results from the chained Celery task
    2. Creates embeds from skill results
    3. Generates a followup message
    4. Publishes followup message to Redis for WebSocket delivery
    
    Args:
        skill_result: The result from the chained skill task (first argument from Celery chain)
        app_id: The app ID that owns the skill
        skill_id: The skill ID that was executed
        chat_id: Optional chat ID for followup message
        message_id: Optional message ID for followup message
        user_id: Optional user ID (UUID)
        user_id_hash: Optional hashed user ID
    
    Returns:
        Dict with processing status
    """
    log_prefix = f"[RATE_LIMIT_FOLLOWUP]"
    logger.info(f"{log_prefix} Starting followup processing for skill '{app_id}.{skill_id}'")
    
    try:
        # skill_result is the result from the chained skill task
        skill_results = skill_result
        if not skill_results:
            error_msg = f"No results from skill task"
            logger.error(f"{log_prefix} {error_msg}")
            return {"status": "error", "message": error_msg}
        
        logger.info(f"{log_prefix} Received skill results from chained task")
        
        # If no chat context, we can't send followup - log and return
        if not chat_id or not message_id:
            logger.warning(
                f"{log_prefix} Missing chat context (chat_id={chat_id}, message_id={message_id}). "
                f"Cannot send followup message. Results available via task polling."
            )
            return {
                "status": "completed",
                "message": "Skill completed but no chat context for followup",
                "results": skill_results
            }
        
        # Initialize services
        cache_service = CacheService()
        directus_service = DirectusService()
        encryption_service = EncryptionService()
        embed_service = EmbedService(cache_service, directus_service, encryption_service)
        
        # Get chat metadata to retrieve user_id and user_id_hash if not provided
        if not user_id or not user_id_hash:
            try:
                chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                if chat_metadata:
                    # Get user_id from chat metadata (hashed_user_id field)
                    hashed_user_id_from_chat = chat_metadata.get("hashed_user_id")
                    if hashed_user_id_from_chat and not user_id_hash:
                        user_id_hash = hashed_user_id_from_chat
                        # Reverse lookup to get user_id
                        if not user_id:
                            user_id = await directus_service.get_user_id_from_hashed_user_id(hashed_user_id_from_chat)
                    logger.info(f"{log_prefix} Retrieved user context from chat: user_id={user_id}, user_id_hash={user_id_hash[:8] if user_id_hash else None}...")
            except Exception as e:
                logger.warning(f"{log_prefix} Could not retrieve user context from chat: {e}")
        
        if not user_id or not user_id_hash:
            logger.warning(
                f"{log_prefix} Missing user context (user_id={user_id}, user_id_hash={user_id_hash}). "
                f"Cannot send followup message. Results available via task polling."
            )
            return {
                "status": "completed",
                "message": "Skill completed but no user context for followup",
                "results": skill_results
            }
        
        # Get user vault key ID for encryption
        user_vault_key_id = None
        try:
            user_data = await directus_service.get_user_by_id(user_id)
            if user_data and "vault_key_id" in user_data:
                user_vault_key_id = user_data["vault_key_id"]
        except Exception as e:
            logger.warning(f"{log_prefix} Could not retrieve user vault key ID: {e}")
        
        # Create embeds from skill results
        # Extract results array from skill response (handles nested structure)
        results_list = []
        if isinstance(skill_results, dict) and "results" in skill_results:
            # Handle nested results structure: {"results": [{"id": 1, "results": [...]}, ...]}
            nested_results = skill_results.get("results", [])
            for nested_result in nested_results:
                if isinstance(nested_result, dict) and "results" in nested_result:
                    results_list.extend(nested_result.get("results", []))
        elif isinstance(skill_results, list):
            results_list = skill_results
        elif isinstance(skill_results, dict):
            # Single result
            results_list = [skill_results]
        
        if results_list:
            logger.info(f"{log_prefix} Creating embeds from {len(results_list)} results")
            embed_data = await embed_service.create_embeds_from_skill_results(
                app_id=app_id,
                skill_id=skill_id,
                results=results_list,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=user_id_hash or "",
                user_vault_key_id=user_vault_key_id or "",
                task_id=None,  # Not needed for followup embeds
                log_prefix=log_prefix
            )
            
            if embed_data:
                logger.info(f"{log_prefix} Created embeds: parent_embed_id={embed_data.get('parent_embed_id')}")
            else:
                logger.warning(f"{log_prefix} Failed to create embeds from skill results")
        
        # Create a new message ID and task ID for the followup message
        import time
        import uuid
        followup_message_id = f"followup_{int(time.time() * 1000)}"
        followup_task_id = str(uuid.uuid4())
        
        # Generate followup message
        # For now, create a simple followup message that references the results
        # The embeds are already created, so they'll be displayed automatically
        # TODO: In the future, we could use main_processor to generate a more natural followup
        logger.info(f"{log_prefix} Generating followup message")
        
        # Create a simple followup message
        # Get skill name for better message
        skill_name = skill_id.replace("_", " ").title()
        if app_id == "web" and skill_id == "search":
            skill_name = "web search"
        elif app_id == "news" and skill_id == "search":
            skill_name = "news search"
        elif app_id == "videos" and skill_id == "search":
            skill_name = "video search"
        elif app_id == "maps" and skill_id == "search":
            skill_name = "place search"
        elif app_id == "web" and skill_id == "read":
            skill_name = "web page reading"
        elif app_id == "videos" and skill_id == "transcript":
            skill_name = "video transcript"
        
        # Count results for message
        result_count = len(results_list) if results_list else 0
        if result_count > 0:
            followup_content = f"I've completed the {skill_name} request. I found {result_count} result{'s' if result_count != 1 else ''}. Here they are:"
        else:
            followup_content = f"I've completed the {skill_name} request, but no results were found."
        
        logger.info(f"{log_prefix} Generated followup message: '{followup_content[:100]}...'")
        
        # Publish followup message to Redis for WebSocket delivery
        # Use the same mechanism as stream_consumer
        redis_channel_name = f"chat_stream::{chat_id}"
        
        # Create payload similar to stream_consumer's _create_redis_payload
        payload = {
            "type": "ai_message_chunk",
            "task_id": followup_task_id,
            "chat_id": chat_id,
            "user_id_uuid": user_id,
            "user_id_hash": user_id_hash,
            "message_id": followup_message_id,
            "user_message_id": message_id,  # Original message that triggered the skill
            "full_content_so_far": followup_content,
            "sequence": 1,
            "is_final_chunk": True,  # This is a complete message, not streaming
            "interrupted_by_soft_limit": False,
            "interrupted_by_revocation": False
        }
        
        # Publish to Redis
        try:
            await cache_service.publish_event(redis_channel_name, payload)
            logger.info(f"{log_prefix} Published followup message to Redis channel '{redis_channel_name}'")
        except Exception as e:
            logger.error(f"{log_prefix} Failed to publish followup message to Redis: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to publish followup message: {str(e)}"
            }
        
        logger.info(f"{log_prefix} Followup processing completed successfully")
        
        return {
            "status": "completed",
            "message": "Followup processing completed",
            "skill_results": skill_results,
            "embeds_created": embed_data is not None
        }
        
    except Exception as e:
        logger.error(f"{log_prefix} Error processing rate limit followup: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Error processing followup: {str(e)}"
        }


@app.task(
    name="apps.ai.tasks.rate_limit_followup",
    bind=True,
    max_retries=3
)
def process_rate_limit_followup_task(
    self,
    skill_result: Any,  # First argument from chain (result of skill task)
    app_id: str,
    skill_id: str,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_id_hash: Optional[str] = None
):
    """
    Celery task wrapper for processing rate-limited skill followup.
    
    This task is automatically chained after rate-limited skill tasks complete.
    It processes the skill results, creates embeds, and sends a followup message.
    
    Args:
        skill_result: The result from the chained skill task (first argument from Celery chain)
        app_id: The app ID that owns the skill
        skill_id: The skill ID that was executed
        chat_id: Optional chat ID for followup message
        message_id: Optional message ID for followup message
        user_id: Optional user ID (UUID)
        user_id_hash: Optional hashed user ID
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN_TASK_ID'
    logger.info(
        f"SYNC_WRAPPER: process_rate_limit_followup_task for skill '{app_id}.{skill_id}', "
        f"chat_id={chat_id}, task_id={task_id}"
    )
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _async_process_rate_limit_followup(
                skill_result=skill_result,
                app_id=app_id,
                skill_id=skill_id,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=user_id_hash
            )
        )
        logger.info(
            f"SYNC_WRAPPER_SUCCESS: process_rate_limit_followup_task completed for skill '{app_id}.{skill_id}', "
            f"task_id={task_id}"
        )
        return result
    except Exception as e:
        logger.error(
            f"SYNC_WRAPPER_ERROR: process_rate_limit_followup_task failed for skill '{app_id}.{skill_id}', "
            f"task_id={task_id}: {e}",
            exc_info=True
        )
        raise  # Re-raise to let Celery handle retries
    finally:
        if loop:
            loop.close()
        logger.info(
            f"TASK_FINALLY_SYNC_WRAPPER: Event loop closed for process_rate_limit_followup_task task_id: {task_id}"
        )

