# backend/apps/ai/tasks/ask_skill_task.py
# Celery task for the AI App's "ask" skill.
#
# IMPORTANT CONTEXT:
# The tasks defined in this file are executed by the 'task-worker' Docker service.
# This worker service has the broader 'backend' codebase (including 'backend/core'
# and 'backend/apps') mounted, allowing it to import modules like
# 'backend.core.api.app.tasks.celery_config'.
# The 'celery_app' imported here is the central Celery application instance
# that the 'task-worker' is configured to use. This is how tasks defined here
# are registered with and executed by that worker.

import logging
import asyncio
import time
import os
import uuid
from typing import Dict, Any, List, Optional
import httpx
from pydantic import ValidationError
from celery.exceptions import Ignore, SoftTimeLimitExceeded
from celery.states import REVOKED as TASK_STATE_REVOKED # Module-level import

# Import Celery app instance
from backend.core.api.app.tasks import celery_config

# Import services to be instantiated directly in the task
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService # Assuming this is the correct path
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_sanitization import sanitize_request_data_for_logging

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_schemas.app_metadata_schemas import AppYAML
from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
from backend.apps.ai.processing.preprocessor import handle_preprocessing, PreprocessingResult
from backend.apps.ai.processing.postprocessor import (
    handle_postprocessing, 
    PostProcessingResult,
    handle_memory_generation,
    extract_settings_memory_categories,
    get_category_schemas,
)
from .stream_consumer import _consume_main_processing_stream

# Import override parser for @ mentioning syntax (e.g., @ai-model:claude-opus-4-5)
from backend.core.api.app.utils.override_parser import parse_overrides_from_messages, UserOverrides

# Import embed service for cleanup on task failure
from backend.core.api.app.services.embed_service import EmbedService


logger = logging.getLogger(__name__)


async def _cleanup_processing_embeds_on_task_failure(
    task_id: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    error_message: str,
    cache_service: Optional[CacheService] = None,
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None,
    use_cancelled_status: bool = False
) -> int:
    """
    Clean up processing embeds when a task fails unexpectedly.
    
    This function finds all embeds in "processing" status that were created by this task
    and marks them as "error" (or "cancelled" if task was revoked by user) so the frontend
    can display the failure state properly.
    
    CRITICAL: This prevents embeds from being stuck in "processing" forever when:
    - Postprocessing LLM fails
    - Task is revoked or times out
    - Any unexpected exception occurs
    
    Args:
        task_id: The Celery task ID (used to find related embeds)
        chat_id: The chat ID where embeds were created
        message_id: The message ID associated with the embeds
        user_id: The user ID (for cache access)
        user_id_hash: The hashed user ID (for Directus storage)
        user_vault_key_id: The vault key ID for encryption
        error_message: Error message to include in the embed status
        cache_service: Optional CacheService instance
        directus_service: Optional DirectusService instance
        encryption_service: Optional EncryptionService instance
        use_cancelled_status: If True, mark embeds as "cancelled" instead of "error" (for user-initiated cancellation)
        
    Returns:
        Number of embeds that were cleaned up
    """
    log_prefix = f"[Task ID: {task_id}, ChatID: {chat_id}] EMBED_CLEANUP"
    cleaned_count = 0
    
    try:
        # Create service instances if not provided
        if not cache_service:
            cache_service = CacheService()
        if not directus_service:
            directus_service = DirectusService()
            await directus_service.ensure_auth_token()
        if not encryption_service:
            encryption_service = EncryptionService()
        
        # Create embed service for cleanup operations
        embed_service = EmbedService(cache_service, directus_service, encryption_service)
        
        # Get all embeds from cache for this chat that might be in processing state
        # We use the cache key pattern to find embeds created during this task
        import hashlib
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest()
        
        # Query cache for processing embeds associated with this task
        # The embed cache key pattern: embed:{embed_id}
        # We need to scan for embeds with hashed_task_id matching this task
        client = await cache_service.client
        if not client:
            logger.warning(f"{log_prefix} Redis client not available for embed cleanup")
            return 0
        
        # Scan for embed keys
        cursor = 0
        embed_keys = []
        while True:
            cursor, keys = await client.scan(cursor, match="embed:*", count=100)
            if keys:
                embed_keys.extend(keys)
            if cursor == 0:
                break
        
        logger.info(f"{log_prefix} Scanning {len(embed_keys)} embed cache entries for processing embeds")
        
        for key in embed_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                embed_data_str = await client.get(key_str)
                if not embed_data_str:
                    continue
                    
                import json
                embed_data = json.loads(embed_data_str.decode('utf-8') if isinstance(embed_data_str, bytes) else embed_data_str)
                
                # Check if this embed:
                # 1. Is in "processing" status
                # 2. Belongs to this chat
                # 3. Was created by this task (hashed_task_id matches)
                embed_status = embed_data.get("status")
                embed_hashed_chat_id = embed_data.get("hashed_chat_id")
                embed_hashed_task_id = embed_data.get("hashed_task_id")
                
                if (embed_status == "processing" and 
                    embed_hashed_chat_id == hashed_chat_id and
                    embed_hashed_task_id == hashed_task_id):
                    
                    embed_id = embed_data.get("embed_id") or key_str.replace("embed:", "")
                    app_id = embed_data.get("app_id", "unknown")
                    skill_id = embed_data.get("skill_id", "unknown")
                    
                    target_status = "cancelled" if use_cancelled_status else "error"
                    logger.info(
                        f"{log_prefix} Found processing embed {embed_id} (app={app_id}, skill={skill_id}) - marking as {target_status}"
                    )
                    
                    # Update embed to error or cancelled status
                    try:
                        if use_cancelled_status:
                            await embed_service.update_embed_status_to_cancelled(
                                embed_id=embed_id,
                                app_id=app_id,
                                skill_id=skill_id,
                                chat_id=chat_id,
                                message_id=message_id,
                                user_id=user_id,
                                user_id_hash=user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                log_prefix=log_prefix
                            )
                        else:
                            await embed_service.update_embed_status_to_error(
                                embed_id=embed_id,
                                app_id=app_id,
                                skill_id=skill_id,
                                error_message=f"Task failed: {error_message}",
                                chat_id=chat_id,
                                message_id=message_id,
                                user_id=user_id,
                                user_id_hash=user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                log_prefix=log_prefix
                            )
                        cleaned_count += 1
                        logger.info(f"{log_prefix} Successfully marked embed {embed_id} as {target_status}")
                    except Exception as update_error:
                        logger.error(f"{log_prefix} Failed to update embed {embed_id} to error: {update_error}")
                        
            except Exception as embed_error:
                logger.warning(f"{log_prefix} Error processing embed key {key}: {embed_error}")
                continue
        
        if cleaned_count > 0:
            logger.info(f"{log_prefix} Cleaned up {cleaned_count} processing embed(s)")
        else:
            logger.debug(f"{log_prefix} No processing embeds found to clean up")
            
    except Exception as e:
        logger.error(f"{log_prefix} Error during embed cleanup: {e}", exc_info=True)
    
    return cleaned_count


async def _cleanup_on_task_failure(
    task_id: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    error_message: str,
    cache_service: Optional[CacheService] = None,
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None,
    use_cancelled_status: bool = False
) -> None:
    """
    Comprehensive cleanup when a task fails unexpectedly.
    
    This function performs two critical cleanup operations:
    1. Clears the active_ai_task marker so the typing indicator stops
    2. Marks processing embeds as error (or cancelled) so they don't get stuck
    
    CRITICAL: This ensures that when a task fails for any reason (timeout, exception,
    revocation, CMS errors, etc.), the user can immediately send new messages
    and the UI reflects the failure properly.
    
    Args:
        task_id: The Celery task ID
        chat_id: The chat ID where the task was running
        message_id: The message ID associated with the task
        user_id: The user ID (for cache access)
        user_id_hash: The hashed user ID (for Directus storage)
        user_vault_key_id: The vault key ID for encryption
        error_message: Error message describing the failure
        cache_service: Optional CacheService instance
        directus_service: Optional DirectusService instance
        encryption_service: Optional EncryptionService instance
        use_cancelled_status: If True, mark embeds as "cancelled" instead of "error"
    """
    log_prefix = f"[Task ID: {task_id}, ChatID: {chat_id}] TASK_CLEANUP"
    
    # Create cache service if not provided
    if not cache_service:
        cache_service = CacheService()
    
    # 1. Clear active_ai_task marker - this is critical for stopping the typing indicator
    try:
        cleared = await cache_service.clear_active_ai_task(chat_id)
        if cleared:
            logger.info(f"{log_prefix} Cleared active_ai_task marker after failure: {error_message}")
        else:
            logger.warning(f"{log_prefix} Failed to clear active_ai_task marker (may not exist)")
    except Exception as e:
        logger.error(f"{log_prefix} Error clearing active_ai_task marker: {e}", exc_info=True)
    
    # 2. Clean up processing embeds
    try:
        cleaned_count = await _cleanup_processing_embeds_on_task_failure(
            task_id=task_id,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            error_message=error_message,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            use_cancelled_status=use_cancelled_status
        )
        if cleaned_count > 0:
            logger.info(f"{log_prefix} Cleaned up {cleaned_count} processing embed(s)")
    except Exception as e:
        logger.error(f"{log_prefix} Error cleaning up embeds: {e}", exc_info=True)


# Note: Avoid internal API lookups per task to keep latency low. We rely on
# the worker-local ConfigManager (see celery_config) and fail fast if configs are missing.

# Internal API configuration for fallback cache refresh
# This is used when discovered_apps_metadata is missing from cache (e.g., cache expired or flushed)
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
INTERNAL_API_TIMEOUT = 10.0  # Timeout for internal API requests in seconds

# Critical apps that should normally be available for full functionality
# If these are missing, the AI will have reduced capabilities
CRITICAL_APPS = ["web", "ai"]


def _check_critical_apps_availability(
    discovered_apps_metadata: Dict[str, AppYAML],
    task_id: str
) -> None:
    """
    Check if critical apps are available and log warnings if they're missing.
    
    This helps diagnose issues where important apps (like 'web') are unavailable,
    which would cause the AI to be instructed about capabilities it doesn't have.
    
    Args:
        discovered_apps_metadata: Dict of discovered app_id -> AppYAML
        task_id: Task ID for logging
    """
    available_app_ids = set(discovered_apps_metadata.keys())
    missing_critical_apps = []
    
    for critical_app in CRITICAL_APPS:
        if critical_app not in available_app_ids:
            missing_critical_apps.append(critical_app)
    
    if missing_critical_apps:
        logger.warning(
            f"[Task ID: {task_id}] [CRITICAL_APPS] WARNING: Critical app(s) NOT AVAILABLE: {', '.join(missing_critical_apps)}. "
            f"Available apps: {', '.join(available_app_ids) if available_app_ids else 'None'}. "
            f"This may indicate app containers are not running or not healthy. "
            f"The AI will NOT have access to these apps' skills (e.g., web-search, web-read if 'web' is missing). "
            f"Check docker-compose logs and the /v1/health endpoint."
        )
    else:
        logger.debug(
            f"[Task ID: {task_id}] [CRITICAL_APPS] All critical apps available: {', '.join(CRITICAL_APPS)}"
        )


async def _fetch_and_cache_apps_metadata(
    cache_service_instance: CacheService,
    task_id: str
) -> Dict[str, AppYAML]:
    """
    Fallback mechanism to fetch discovered apps metadata from the API when cache is empty.
    
    This handles cases where the cache has expired or been flushed while the API is still running.
    The API's /apps/metadata endpoint returns all discovered apps, and we re-cache them here.
    
    CRITICAL: Without this fallback, the LLM has NO tools available (no web search, etc.)
    when the cache expires. This resulted in the LLM hallucinating search results instead
    of actually executing tool calls.
    
    Args:
        cache_service_instance: CacheService instance for caching
        task_id: Task ID for logging
        
    Returns:
        Dict of app_id -> AppYAML, or empty dict if fetch fails
    """
    log_prefix = f"[Task ID: {task_id}]"
    
    try:
        # Prepare request headers
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        
        url = f"{INTERNAL_API_BASE_URL}/apps/metadata"
        logger.info(f"{log_prefix} Attempting to fetch discovered_apps_metadata from API: {url}")
        
        async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            apps_data = data.get("apps", {})
            
            if not apps_data:
                logger.warning(f"{log_prefix} API returned empty apps metadata")
                return {}
            
            # Parse the raw dict into AppYAML models
            discovered_apps_metadata: Dict[str, AppYAML] = {}
            for app_id, app_dict in apps_data.items():
                try:
                    discovered_apps_metadata[app_id] = AppYAML(**app_dict)
                except Exception as e:
                    logger.warning(f"{log_prefix} Failed to parse app '{app_id}' metadata: {e}")
                    continue
            
            # Re-cache the metadata for future tasks
            if discovered_apps_metadata and cache_service_instance:
                try:
                    await cache_service_instance.set_discovered_apps_metadata(discovered_apps_metadata)
                    logger.info(f"{log_prefix} Successfully re-cached discovered_apps_metadata ({len(discovered_apps_metadata)} apps)")
                except Exception as e_cache:
                    logger.error(f"{log_prefix} Failed to re-cache discovered_apps_metadata: {e_cache}")
            
            return discovered_apps_metadata
            
    except httpx.HTTPStatusError as e:
        logger.error(f"{log_prefix} HTTP error fetching apps metadata: {e.response.status_code} - {e.response.text}")
        return {}
    except httpx.RequestError as e:
        logger.error(f"{log_prefix} Request error fetching apps metadata: {e}")
        return {}
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error fetching apps metadata: {e}", exc_info=True)
        return {}


# Custom exception for retry logic
class ChatNotFoundError(Exception):
    """Custom exception to trigger Celery retry when a chat is not found in the database."""
    pass

async def _async_process_ai_skill_ask_task(
    task_id: str, # task_id is still needed
    request_data: AskSkillRequest,
    skill_config: AskSkillDefaultConfig
):
    """
    Asynchronous core logic for processing the AI skill ask task.
    Initializes services and performs the main processing steps.
    Returns a dictionary with processing results and status flags.
    """
    logger.info(f"[Task ID: {task_id}] Async task execution started.")

    # Local flags for interruption, to be returned
    task_was_revoked = False
    task_was_soft_limited = False

    # --- Initialize services ---
    # PERFORMANCE OPTIMIZATION: Use worker-level cache service for connection pooling
    # This eliminates ~100-200ms of Redis connection overhead per task
    secrets_manager = None
    cache_service_instance = None
    directus_service_instance = None
    encryption_service_instance = None

    try:
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        logger.info(f"[Task ID: {task_id}] SecretsManager initialized.")

        # PERFORMANCE OPTIMIZATION: Try to use worker-level cache service first
        # Falls back to creating a new instance if the worker-level service is unavailable
        try:
            from backend.core.api.app.tasks.celery_config import get_worker_cache_service
            cache_service_instance = await get_worker_cache_service()
            logger.info(f"[Task ID: {task_id}] Using worker-level CacheService (connection pooling)")
        except Exception as e:
            logger.warning(f"[Task ID: {task_id}] Could not get worker-level CacheService ({e}), creating new instance")
            cache_service_instance = CacheService()
            await cache_service_instance.client 
            logger.info(f"[Task ID: {task_id}] CacheService initialized (new instance)")
        
        encryption_service_instance = EncryptionService(
            cache_service=cache_service_instance
        )
        logger.info(f"[Task ID: {task_id}] EncryptionService initialized.")

        directus_service_instance = DirectusService(
            cache_service=cache_service_instance,
            encryption_service=encryption_service_instance 
        )
        logger.info(f"[Task ID: {task_id}] DirectusService initialized.")

    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Failed to initialize services: {e}", exc_info=True)
        
        # Notify the API via Redis stream that a fatal error occurred
        if cache_service_instance:
            try:
                error_payload = {
                    "type": "ai_message_chunk",
                    "task_id": task_id,
                    "chat_id": request_data.chat_id,
                    "full_content_so_far": f"Error: {str(e)}",
                    "is_final_chunk": True,
                    "error": True
                }
                await cache_service_instance.publish_event(f"chat_stream::{request_data.chat_id}", error_payload)
            except Exception:
                pass
                
        raise RuntimeError(f"Service initialization failed: {e}")


    # --- Load configurations from cache (preloaded by main API server at startup) ---
    # The main API server preloads these into the shared Dragonfly cache during startup.
    # Task workers read from cache to avoid disk I/O and ensure consistency across containers.
    # Fallback to disk loading if cache is empty (e.g., cache expired or server restarted).
    
    base_instructions: Dict[str, Any] = {}
    try:
        if cache_service_instance:
            cached_base_instructions = await cache_service_instance.get_base_instructions()
            if cached_base_instructions:
                base_instructions = cached_base_instructions
                logger.info(f"[Task ID: {task_id}] Successfully loaded base_instructions from cache (preloaded by main API server).")
            else:
                # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                logger.warning(f"[Task ID: {task_id}] base_instructions not found in cache. Loading from disk and re-caching...")
                base_instructions = load_base_instructions()
                if base_instructions:
                    try:
                        await cache_service_instance.set_base_instructions(base_instructions)
                        logger.info(f"[Task ID: {task_id}] Re-cached base_instructions after disk load.")
                    except Exception as e:
                        logger.warning(f"[Task ID: {task_id}] Failed to re-cache base_instructions: {e}")
        else:
            # No cache service available, load from disk
            logger.warning(f"[Task ID: {task_id}] CacheService not available. Loading base_instructions from disk...")
            base_instructions = load_base_instructions()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error loading base_instructions: {e}", exc_info=True)
        # Fallback to disk loading
        base_instructions = load_base_instructions()
    
    if not base_instructions:
        logger.error(f"[Task ID: {task_id}] Failed to load base_instructions.yml from cache or disk. Aborting task.")
        # Sync wrapper handles Celery state update
        raise RuntimeError("base_instructions.yml not found or empty.")

    all_mates_configs: List[MateConfig] = []
    try:
        if cache_service_instance:
            cached_mates_configs = await cache_service_instance.get_mates_configs()
            if cached_mates_configs:
                all_mates_configs = cached_mates_configs
                logger.info(f"[Task ID: {task_id}] Successfully loaded {len(all_mates_configs)} mates_configs from cache (preloaded by main API server).")
            else:
                # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                logger.warning(f"[Task ID: {task_id}] mates_configs not found in cache. Loading from disk and re-caching...")
                all_mates_configs = load_mates_config()
                if all_mates_configs:
                    try:
                        await cache_service_instance.set_mates_configs(all_mates_configs)
                        logger.info(f"[Task ID: {task_id}] Re-cached {len(all_mates_configs)} mates_configs after disk load.")
                    except Exception as e:
                        logger.warning(f"[Task ID: {task_id}] Failed to re-cache mates_configs: {e}")
        else:
            # No cache service available, load from disk
            logger.warning(f"[Task ID: {task_id}] CacheService not available. Loading mates_configs from disk...")
            all_mates_configs = load_mates_config()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error loading mates_configs: {e}", exc_info=True)
        # Fallback to disk loading
        all_mates_configs = load_mates_config()
    
    if not all_mates_configs:
        logger.critical(f"[Task ID: {task_id}] Failed to load mates_config.yml from cache or disk. Aborting task.")
        # Sync wrapper handles Celery state update
        raise RuntimeError("mates.yml not found, empty, or invalid.")

    # --- Load discovered_apps_metadata from cache (with fallback to API) ---
    # CRITICAL: Without discovered_apps_metadata, the LLM has NO tools available (no web search, etc.)
    # This can result in the LLM hallucinating tool results instead of actually calling them.
    discovered_apps_metadata: Dict[str, AppYAML] = {}
    try:
        if cache_service_instance:
            cached_metadata = await cache_service_instance.get_discovered_apps_metadata()
            if cached_metadata:
                discovered_apps_metadata = cached_metadata
                # Log discovered apps and their skills for debugging
                app_names = list(discovered_apps_metadata.keys())
                logger.info(f"[Task ID: {task_id}] Successfully loaded discovered_apps_metadata from cache via CacheService method.")
                logger.info(f"[Task ID: {task_id}] Discovered apps ({len(app_names)} total): {', '.join(app_names) if app_names else 'None'}")
                for app_id, metadata in discovered_apps_metadata.items():
                    skill_ids = [skill.id for skill in metadata.skills] if metadata.skills else []
                    skill_identifiers = [f"{app_id}.{skill_id}" for skill_id in skill_ids]
                    logger.info(f"[Task ID: {task_id}]   App '{app_id}': Skills: {', '.join(skill_identifiers) if skill_identifiers else 'None'}")
                
                # Check for critical apps that should normally be available
                _check_critical_apps_availability(discovered_apps_metadata, task_id)
            else:
                # FALLBACK: Cache is empty (expired or flushed) - fetch from API and re-cache
                # This prevents the LLM from having no tools available due to cache expiration
                logger.warning(f"[Task ID: {task_id}] discovered_apps_metadata not found in cache. Attempting fallback to API...")
                discovered_apps_metadata = await _fetch_and_cache_apps_metadata(cache_service_instance, task_id)
                
                if discovered_apps_metadata:
                    app_names = list(discovered_apps_metadata.keys())
                    logger.info(f"[Task ID: {task_id}] Successfully fetched discovered_apps_metadata from API fallback.")
                    logger.info(f"[Task ID: {task_id}] Discovered apps ({len(app_names)} total): {', '.join(app_names) if app_names else 'None'}")
                    
                    # Warn if only one app is discovered (likely indicates other apps are not running/available)
                    if len(app_names) == 1:
                        logger.warning(
                            f"[Task ID: {task_id}] WARNING: Only one app discovered ({app_names[0]}). "
                            f"This may indicate that other app containers are not running or not responding to /metadata endpoint. "
                            f"Check docker-compose logs and ensure all app containers (app-web, app-ai, etc.) are healthy."
                        )
                    
                    for app_id, metadata in discovered_apps_metadata.items():
                        skill_ids = [skill.id for skill in metadata.skills] if metadata.skills else []
                        skill_identifiers = [f"{app_id}-{skill_id}" for skill_id in skill_ids]  # Use hyphen format for consistency
                        logger.info(f"[Task ID: {task_id}]   App '{app_id}': Skills: {', '.join(skill_identifiers) if skill_identifiers else 'None'}")
                    
                    # Check for critical apps that should normally be available
                    _check_critical_apps_availability(discovered_apps_metadata, task_id)
                else:
                    logger.error(
                        f"[Task ID: {task_id}] CRITICAL: Failed to load discovered_apps_metadata from both cache and API. "
                        f"LLM will have NO tools available! This will cause the LLM to hallucinate tool results instead of actually calling them. "
                        f"Check that the API service is running and /apps/metadata endpoint is accessible."
                    )
        else:
            logger.error(f"[Task ID: {task_id}] CacheService instance not available for loading discovered_apps_metadata.")
    except Exception as e_cache_get:
        logger.error(f"[Task ID: {task_id}] Error calling get_discovered_apps_metadata: {e_cache_get}", exc_info=True)

    # --- Fetch user_vault_key_id and warm cache ---
    # This supports internal users (Web App) who may not have logged in via web app to trigger cache warming.
    # We ALWAYS need the user record and credits for the pre-processing credit check.
    # Credits are encrypted, so the vault_key_id is mandatory for all billable requests.
    user_vault_key_id: Optional[str] = None
    if cache_service_instance and request_data.user_id:
        cached_user_data = await cache_service_instance.get_user_by_id(request_data.user_id)
        
        if not cached_user_data:
            # ON-DEMAND CACHE WARMING: User not in cache, fetch from Directus and cache.
            # This is required for both internal and external requests to check balance.
            logger.info(f"[Task ID: {task_id}] User not in cache, warming cache for user_id: {request_data.user_id}")
            try:
                if directus_service_instance:
                    # Fetch user data using /users/{id} endpoint (NOT /items/users which requires special permissions)
                    # The get_user_fields_direct method correctly uses the /users/{id} endpoint
                    # which the admin token can access for any user
                    user_record = await directus_service_instance.get_user_fields_direct(
                        request_data.user_id,
                        fields=['id', 'vault_key_id', 'encrypted_username', 'encrypted_credit_balance']
                    )
                    
                    if user_record:
                        cache_data = {
                            'id': user_record.get('id') or request_data.user_id,
                            'user_id': user_record.get('id') or request_data.user_id,
                            'vault_key_id': user_record.get('vault_key_id'),
                            'encrypted_username': user_record.get('encrypted_username'),
                            'encrypted_credit_balance': user_record.get('encrypted_credit_balance'),
                            '_api_warmed': True
                        }
                        
                        # MANDATORY: Decrypt credits for the cache so preprocessor can check balance
                        # Field name is 'encrypted_credit_balance' (not 'encrypted_credits')
                        if user_record.get('encrypted_credit_balance') and user_record.get('vault_key_id'):
                            try:
                                decrypted_credits_str = await directus_service_instance.encryption_service.decrypt_with_user_key(
                                    user_record.get('encrypted_credit_balance'), 
                                    user_record.get('vault_key_id')
                                )
                                if decrypted_credits_str:
                                    cache_data['credits'] = int(decrypted_credits_str)
                                    logger.info(f"[Task ID: {task_id}] Successfully decrypted credits for user {request_data.user_id}: {cache_data['credits']}")
                            except Exception as e_dec:
                                logger.error(f"[Task ID: {task_id}] Failed to decrypt credits: {e_dec}")
                                # If we can't decrypt credits, we can't safely proceed
                                raise RuntimeError(f"Could not decrypt user credits: {e_dec}")
                        
                        await cache_service_instance.set_user(cache_data, user_id=request_data.user_id)
                        cached_user_data = cache_data
                    else:
                        logger.error(f"[Task ID: {task_id}] User not found in Directus: {request_data.user_id}")
                        raise RuntimeError(f"User not found: {request_data.user_id}")
                else:
                    raise RuntimeError("DirectusService not available for cache warming")
            except Exception as e:
                logger.error(f"[Task ID: {task_id}] Cache warming failed: {e}", exc_info=True)
                # Notify the API via Redis stream so it doesn't hang
                if cache_service_instance:
                    try:
                        error_payload = {
                            "type": "ai_message_chunk",
                            "task_id": task_id,
                            "chat_id": request_data.chat_id,
                            "full_content_so_far": "Error: User identification or credit check failed.",
                            "is_final_chunk": True,
                            "error": True
                        }
                        await cache_service_instance.publish_event(f"chat_stream::{request_data.chat_id}", error_payload)
                    except Exception:
                        pass
                raise RuntimeError(f"Failed to identify user or check credits: {e}")

        user_vault_key_id = cached_user_data.get("vault_key_id")
        if not user_vault_key_id:
            logger.error(f"[Task ID: {task_id}] vault_key_id not found for user {request_data.user_id}. Aborting.")
            raise RuntimeError("User vault key ID not found.")
            
    elif not cache_service_instance:
        logger.error(f"[Task ID: {task_id}] CacheService not available.")
        raise RuntimeError("CacheService not available.")
    elif not request_data.user_id:
        logger.error(f"[Task ID: {task_id}] user_id is missing.")
        raise RuntimeError("user_id is missing.")

    # Parse app settings/memories metadata from client
    # CLIENT IS THE SOURCE OF TRUTH - only the client can decrypt this data
    # Format from client: ["code-preferred_technologies", "travel-trips", ...]
    # Convert to dict format for preprocessor: { "app_id": ["item_type1", "item_type2"], ... }
    user_app_memories_metadata: Dict[str, List[str]] = {}
    if request_data.app_settings_memories_metadata:
        for key in request_data.app_settings_memories_metadata:
            if not isinstance(key, str):
                logger.warning(f"[Task ID: {task_id}] Invalid app_settings_memories_metadata key (not a string): {key}")
                continue
            
            # Parse "app_id-item_type" format
            dash_index = key.find('-')
            if dash_index == -1:
                logger.warning(f"[Task ID: {task_id}] Invalid app_settings_memories_metadata key format (no hyphen): {key}")
                continue
            
            app_id = key[:dash_index]
            item_type = key[dash_index + 1:]
            
            if not app_id or not item_type:
                logger.warning(f"[Task ID: {task_id}] Invalid app_settings_memories_metadata key (empty parts): {key}")
                continue
            
            if app_id not in user_app_memories_metadata:
                user_app_memories_metadata[app_id] = []
            if item_type not in user_app_memories_metadata[app_id]:
                user_app_memories_metadata[app_id].append(item_type)
        
        if user_app_memories_metadata:
            logger.info(f"[Task ID: {task_id}] Parsed client-provided app_settings_memories_metadata: {len(user_app_memories_metadata)} apps, {sum(len(keys) for keys in user_app_memories_metadata.values())} total keys")
        else:
            logger.debug(f"[Task ID: {task_id}] Client provided app_settings_memories_metadata but no valid keys found.")
    else:
        logger.debug(f"[Task ID: {task_id}] No app_settings_memories_metadata provided by client.")

    # --- Step 0: Parse User Overrides (@ Mentioning) ---
    # Parse user messages for override syntax like @ai-model:claude-opus, @mate:coder, etc.
    # These overrides allow users to manually select AI models, mates, skills, or focus modes.
    # The overrides are applied later in preprocessing to skip automatic selection where specified.
    user_overrides: Optional[UserOverrides] = None
    try:
        if request_data.message_history:
            # Convert AIHistoryMessage objects to dicts for parsing
            message_dicts = [
                {"role": msg.role, "content": msg.content}
                for msg in request_data.message_history
            ]
            user_overrides, cleaned_messages = parse_overrides_from_messages(
                message_dicts,
                log_prefix=f"[Task ID: {task_id}]"
            )

            if user_overrides and user_overrides.has_overrides:
                logger.info(
                    f"[Task ID: {task_id}] USER_OVERRIDE: Detected user overrides. "
                    f"model_id={user_overrides.model_id}, "
                    f"model_provider={user_overrides.model_provider}, "
                    f"mate_id={user_overrides.mate_id}, "
                    f"skills={user_overrides.skills}, "
                    f"focus_modes={user_overrides.focus_modes}"
                )

                # Update the last user message with cleaned content (override syntax removed)
                # This ensures the LLM sees the actual query without the override commands
                if cleaned_messages:
                    for i in range(len(request_data.message_history) - 1, -1, -1):
                        if request_data.message_history[i].role == "user":
                            # Update the content of the Pydantic model directly
                            request_data.message_history[i].content = cleaned_messages[i]["content"]
                            logger.debug(
                                f"[Task ID: {task_id}] Updated last user message content "
                                f"after removing override syntax. New length: {len(cleaned_messages[i]['content'])}"
                            )
                            break
    except Exception as e_override:
        logger.warning(
            f"[Task ID: {task_id}] Failed to parse user overrides (non-fatal): {e_override}. "
            f"Proceeding without overrides."
        )
        user_overrides = None

    # --- Step 1: Preprocessing ---
    # The synchronous wrapper (process_ai_skill_ask_task) will call self.update_state for PROGRESS.
    logger.info(f"[Task ID: {task_id}] Starting preprocessing step...")
    logger.info(f"[Task ID: {task_id}] Chat has title flag from request_data: {request_data.chat_has_title}")

    preprocessing_result: Optional[PreprocessingResult] = None
    try:
        if not cache_service_instance:
            logger.error(f"[Task ID: {task_id}] CacheService instance is not available. Cannot proceed with preprocessing credit check.")
            raise RuntimeError("CacheService not available for preprocessing.")

        preprocessing_result = await handle_preprocessing(
            request_data=request_data, # This now contains chat_has_title boolean flag from the client
            skill_config=skill_config,
            base_instructions=base_instructions,
            cache_service=cache_service_instance,
            secrets_manager=secrets_manager,
            directus_service=directus_service_instance, # Passed for reuse
            encryption_service=encryption_service_instance, # Passed for reuse
            user_app_settings_and_memories_metadata=user_app_memories_metadata,
            discovered_apps_metadata=discovered_apps_metadata,  # Pass discovered apps for tool preselection
            user_overrides=user_overrides  # Pass user overrides from @ mentioning syntax
        )

        # --- Cache debug data for preprocessing stage ---
        # This caches the last 10 requests for debugging purposes (encrypted, 30-minute TTL)
        # IMPORTANT: Store FULL content to enable proper debugging of the AI decision process
        try:
            if cache_service_instance and encryption_service_instance:
                # Prepare preprocessor input data with FULL message history for debugging
                # Convert message history to serializable format
                message_history_serialized = None
                if request_data.message_history:
                    message_history_serialized = [
                        msg.model_dump() if hasattr(msg, 'model_dump') else (
                            {"role": msg.role, "content": msg.content, "created_at": msg.created_at, 
                             "sender_name": getattr(msg, 'sender_name', None), "category": getattr(msg, 'category', None)}
                            if hasattr(msg, 'role') else msg
                        )
                        for msg in request_data.message_history
                    ]
                
                preprocessor_input = {
                    "chat_id": request_data.chat_id,
                    "message_id": request_data.message_id,
                    "user_id": request_data.user_id,
                    "user_id_hash": request_data.user_id_hash,
                    "chat_has_title": request_data.chat_has_title,
                    "mate_id": request_data.mate_id,
                    "active_focus_id": request_data.active_focus_id,
                    "user_preferences": request_data.user_preferences,
                    # FULL message history for debugging
                    "message_history": message_history_serialized,
                    "message_history_count": len(request_data.message_history) if request_data.message_history else 0,
                    # Skill config
                    "skill_config": skill_config.model_dump() if skill_config else None,
                    # Discovered apps metadata
                    "discovered_apps_count": len(discovered_apps_metadata) if discovered_apps_metadata else 0,
                    "discovered_app_ids": list(discovered_apps_metadata.keys()) if discovered_apps_metadata else [],
                    # Base instructions keys (not full content to save space, but track what was used)
                    "base_instructions_keys": list(base_instructions.keys()) if base_instructions else [],
                    # App settings and memories metadata from client (what's available to choose from)
                    # Raw format from client: ["code-preferred_technologies", "travel-trips", ...]
                    "app_settings_memories_metadata_from_client": request_data.app_settings_memories_metadata,
                    "app_settings_memories_metadata_from_client_count": len(request_data.app_settings_memories_metadata) if request_data.app_settings_memories_metadata else 0,
                    # Parsed format used by preprocessor: { "app_id": ["item_type1", "item_type2"], ... }
                    "user_app_memories_metadata_parsed": user_app_memories_metadata,
                    "user_app_memories_metadata_parsed_apps_count": len(user_app_memories_metadata) if user_app_memories_metadata else 0,
                    "user_app_memories_metadata_parsed_total_keys": sum(len(keys) for keys in user_app_memories_metadata.values()) if user_app_memories_metadata else 0,
                }
                
                # Prepare preprocessor output data (full model dump)
                preprocessor_output = preprocessing_result.model_dump() if preprocessing_result else None
                
                await cache_service_instance.cache_debug_request_entry(
                    encryption_service=encryption_service_instance,
                    task_id=task_id,
                    chat_id=request_data.chat_id,
                    user_id=request_data.user_id,
                    stage="preprocessor",
                    input_data=preprocessor_input,
                    output_data=preprocessor_output,
                )
                logger.debug(f"[Task ID: {task_id}] Cached preprocessor debug data (admin only)")
        except Exception as e_debug:
            # Don't fail the task if debug caching fails - just log the error
            logger.warning(f"[Task ID: {task_id}] Failed to cache preprocessor debug data (non-fatal): {e_debug}")

        # Note: We no longer handle harmful content rejection here.
        # Instead, we let it flow through to the stream consumer which will handle it properly
        # with the normal streaming flow, ensuring the frontend gets proper completion signals.
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error during preprocessing: {e}", exc_info=True)
        raise RuntimeError(f"Preprocessing failed: {e}")

    # --- User override: start focus mode from @focus:app_id:focus_id ---
    # When the user explicitly mentions exactly one focus mode, set it as active for this request
    # so the main processor injects the focus prompt and the model runs in that focus.
    if user_overrides and len(user_overrides.focus_modes) == 1:
        app_id, focus_id = user_overrides.focus_modes[0]
        requested_focus_id = f"{app_id}-{focus_id}"
        request_data.active_focus_id = requested_focus_id
        logger.info(
            f"[Task ID: {task_id}] USER_OVERRIDE: Set active_focus_id from @focus to '{requested_focus_id}' for this request."
        )

    # --- Billing preflight validation ---
    # Ensure that we have pricing info configured for the selected provider/model BEFORE we start streaming.
    # Skip preflight entirely if preprocessing says we cannot proceed (e.g., insufficient credits, harmful content).
    if preprocessing_result and preprocessing_result.can_proceed:
        try:
            if not preprocessing_result.selected_main_llm_model_id:
                raise RuntimeError("Selected main LLM model id missing from preprocessing result.")

            full_model_id: str = preprocessing_result.selected_main_llm_model_id
            # Expected format: "provider/model_name" (e.g., "openai/gpt-5"). Never assume a default provider.
            if "/" in full_model_id:
                provider_prefix, model_suffix = full_model_id.split("/", 1)  # Keep nested model ids intact for pricing lookup
            else:
                raise RuntimeError(
                    f"Model id '{full_model_id}' must include a provider prefix (format 'provider/model')."
                )

            # Validate provider pricing exists via local worker ConfigManager only.
            if not celery_config.config_manager:
                raise RuntimeError("Global ConfigManager not initialized in worker. Provider pricing unavailable.")

            provider_pricing_cfg = celery_config.config_manager.get_provider_config(provider_prefix)
            if not provider_pricing_cfg:
                raise RuntimeError(
                    f"Pricing configuration missing for provider '{provider_prefix}'. Ensure '/app/backend/providers/{provider_prefix}.yml' is mounted for the worker."
                )

            model_pricing_details = celery_config.config_manager.get_model_pricing(provider_prefix, model_suffix)
            if not model_pricing_details:
                raise RuntimeError(
                    f"Pricing details missing for model '{model_suffix}' under provider '{provider_prefix}'. "
                    f"Add the model with a 'pricing' section to '/app/backend/providers/{provider_prefix}.yml'."
                )

            logger.info(
                f"[Task ID: {task_id}] Billing preflight validation passed for provider='{provider_prefix}', model='{model_suffix}'."
            )
        except Exception as billing_preflight_exc:
            logger.critical(
                f"[Task ID: {task_id}] Billing preflight validation failed: {billing_preflight_exc}",
                exc_info=True,
            )
            # Fail early to prevent unbillable processing
            raise RuntimeError(f"Billing preflight failed: {billing_preflight_exc}")
    else:
        logger.info(f"[Task ID: {task_id}] Skipping billing preflight: preprocessing.can_proceed is False (reason: {getattr(preprocessing_result, 'rejection_reason', None)}).")

    # --- Handle Title and Mates Update (after preprocessing) ---
    # Note: We now handle title/mates updates for both successful and harmful content cases
    # since harmful content still gets processed through the stream consumer
    # Title and metadata will be sent via ai_typing_started event below

    # --- Notify client that main processing (typing) is starting ---
    # Note: We send typing indicator for successful and harmful content cases
    # since harmful content gets processed through the stream consumer with a predefined response.
    # SKIP for insufficient_credits: these generate a system notice (not an assistant response),
    # so showing a typing indicator would misleadingly look like a regular assistant is responding.
    should_send_typing = (
        preprocessing_result.rejection_reason != "insufficient_credits"
        and preprocessing_result.rejection_reason != "internal_error_llm_preprocessing_failed"
    ) if preprocessing_result else True
    if preprocessing_result and cache_service_instance and should_send_typing:
        try:
            # Use category from preprocessing_result for typing indicator
            typing_category = preprocessing_result.category or "general_knowledge" # Default if category is None
            # Get model_name from preprocessing_result
            # CRITICAL: For error messages (e.g. insufficient credits), we don't show a model name
            model_name = preprocessing_result.selected_main_llm_model_name if preprocessing_result.can_proceed else None
            
            # Extract provider from the selected_main_llm_model_id (format: "provider/model")
            # Then get the actual server (e.g., Cerebras) from the provider config
            # CRITICAL: We must always extract a real server/provider name, never default to "AI"
            provider_name = None  # Will be set from config
            server_region = None  # Will be set from config (e.g., "EU", "US", "APAC")
            
            if preprocessing_result.selected_main_llm_model_id:
                logger.info(f"[Task ID: {task_id}] Starting provider name extraction from model_id: '{preprocessing_result.selected_main_llm_model_id}'")
                model_id_parts = preprocessing_result.selected_main_llm_model_id.split("/", 1)
                if len(model_id_parts) == 2:
                    provider_id = model_id_parts[0]
                    model_id = model_id_parts[1]
                    logger.debug(f"[Task ID: {task_id}] Parsed provider_id='{provider_id}', model_id='{model_id}'")
                    
                    # Get the actual server running the model from ConfigManager
                    if celery_config.config_manager:
                        provider_config = celery_config.config_manager.get_provider_config(provider_id)
                        if provider_config and 'models' in provider_config:
                            logger.debug(f"[Task ID: {task_id}] Provider config found for '{provider_id}', has {len(provider_config['models'])} model(s)")
                            # Find the model in the provider config
                            model_found = False
                            available_model_ids = [m.get('id') for m in provider_config['models']]
                            logger.debug(f"[Task ID: {task_id}] Searching for model_id='{model_id}' in available models: {available_model_ids}")
                            for model_cfg in provider_config['models']:
                                if model_cfg.get('id') == model_id:
                                    model_found = True
                                    # Get the default_server (e.g., "cerebras")
                                    default_server_id = model_cfg.get('default_server')
                                    logger.debug(f"[Task ID: {task_id}] Model '{model_id}' has default_server='{default_server_id}', servers list exists: {'servers' in model_cfg}")
                                    
                                    if default_server_id and 'servers' in model_cfg:
                                        # Find the server entry and get its name
                                        server_found = False
                                        servers_list = model_cfg['servers']
                                        logger.debug(f"[Task ID: {task_id}] Searching for server '{default_server_id}' in {len(servers_list)} server(s): {[s.get('id') for s in servers_list]}")
                                        
                                        for server in servers_list:
                                            server_id = server.get('id')
                                            logger.debug(f"[Task ID: {task_id}] Checking server id '{server_id}' against default_server '{default_server_id}' (match: {server_id == default_server_id})")
                                            if server_id == default_server_id:
                                                provider_name = server.get('name')
                                                server_region = server.get('region')  # e.g., "EU", "US", "APAC"
                                                logger.debug(f"[Task ID: {task_id}] Server match found! Server name: '{provider_name}', region: '{server_region}'")
                                                if not provider_name:
                                                    # Server name not set, use capitalized server ID
                                                    provider_name = default_server_id.capitalize()
                                                    logger.warning(f"[Task ID: {task_id}] Server '{default_server_id}' found but has no 'name' field, using capitalized ID '{provider_name}'")
                                                else:
                                                    logger.info(f"[Task ID: {task_id}] ✅ Successfully extracted server name '{provider_name}', region '{server_region}' for default_server '{default_server_id}' in model '{model_id}'")
                                                server_found = True
                                                break
                                        if not server_found:
                                            # Server not found in servers list, use capitalized server ID
                                            provider_name = default_server_id.capitalize()
                                            logger.warning(f"[Task ID: {task_id}] Server '{default_server_id}' not found in servers list for model '{model_id}'. Available server IDs: {[s.get('id') for s in servers_list]}. Using capitalized ID '{provider_name}'")
                                    else:
                                        # Model found but no default_server or servers configured
                                        # Fallback to provider name from provider config
                                        provider_name = provider_config.get('name') or provider_id.capitalize()
                                        if not default_server_id:
                                            logger.warning(f"[Task ID: {task_id}] Model '{model_id}' has no default_server configured, using provider name '{provider_name}'")
                                        else:
                                            logger.warning(f"[Task ID: {task_id}] Model '{model_id}' has no servers list configured, using provider name '{provider_name}'")
                                    break
                            
                            if not model_found:
                                # Model not found in config, fallback to provider name from provider config
                                provider_name = provider_config.get('name') or provider_id.capitalize()
                                logger.warning(f"[Task ID: {task_id}] Model '{model_id}' not found in provider '{provider_id}' config, using provider name '{provider_name}'")
                        elif provider_config:
                            # Provider config exists but no models list, use provider name
                            provider_name = provider_config.get('name') or provider_id.capitalize()
                            logger.warning(f"[Task ID: {task_id}] Provider '{provider_id}' config has no models list, using provider name '{provider_name}'")
                        else:
                            # Provider config not found, use capitalized provider ID as fallback
                            provider_name = provider_id.capitalize()
                            logger.warning(f"[Task ID: {task_id}] Provider config not found for '{provider_id}', using capitalized provider ID '{provider_name}'")
                    else:
                        # ConfigManager not available, use capitalized provider ID as fallback
                        provider_name = provider_id.capitalize()
                        logger.warning(f"[Task ID: {task_id}] ConfigManager not available, using capitalized provider ID '{provider_name}'")
                    
                    logger.debug(f"[Task ID: {task_id}] Final provider name: '{provider_name}' from model_id '{preprocessing_result.selected_main_llm_model_id}'")
                else:
                    # Model ID doesn't have expected format (provider/model)
                    # Try to extract provider from the beginning of the string
                    logger.warning(f"[Task ID: {task_id}] Model ID '{preprocessing_result.selected_main_llm_model_id}' doesn't have expected format 'provider/model'.")
                    # Use the first part as provider ID if it exists
                    if model_id_parts and len(model_id_parts) > 0:
                        potential_provider = model_id_parts[0]
                        provider_name = potential_provider.capitalize()
                        logger.warning(f"[Task ID: {task_id}] Using extracted provider ID '{provider_name}' from malformed model ID")
                    else:
                        # Last resort: use the whole model ID as provider name
                        provider_name = preprocessing_result.selected_main_llm_model_id.capitalize()
                        logger.warning(f"[Task ID: {task_id}] Using entire model ID as provider name '{provider_name}'")
            else:
                # selected_main_llm_model_id is None - this is a critical error, but we still need a fallback
                logger.error(f"[Task ID: {task_id}] selected_main_llm_model_id is None or empty! Cannot determine provider name. This should not happen.")
                # Try to get provider name from category or other sources
                # As absolute last resort, use the category name
                if preprocessing_result.category:
                    provider_name = preprocessing_result.category.capitalize()
                    logger.warning(f"[Task ID: {task_id}] Using category '{provider_name}' as provider name fallback")
                else:
                    # This should never happen in normal operation
                    provider_name = "Unknown"
                    logger.error(f"[Task ID: {task_id}] No provider name could be determined! Using 'Unknown' as last resort.")
            
            # Final validation - ensure we have a provider name
            if not provider_name:
                logger.error(f"[Task ID: {task_id}] CRITICAL: provider_name is still None after all extraction attempts!")
                provider_name = "Unknown"
            
            # Persist server provider/region on preprocessing_result so stream_consumer.py
            # can include them in usage_details for billing persistence to the usage collection
            preprocessing_result.server_provider_name = provider_name
            preprocessing_result.server_region = server_region
            
            # Log the final provider name and server region that will be sent to client
            logger.info(f"[Task ID: {task_id}] Provider name to send to client: '{provider_name}', server region: '{server_region}'")
            
            # Build typing payload with conditional metadata (only for new chats)
            typing_payload_data = { 
                "type": "ai_processing_started_event", 
                "event_for_client": "ai_typing_started", 
                "task_id": task_id, # This is the AI's message_id for the new message being generated
                "chat_id": request_data.chat_id,
                "user_id_uuid": request_data.user_id, # Actual user ID for routing
                "user_id_hash": request_data.user_id_hash, # Hashed user ID for logging/internal use
                "user_message_id": request_data.message_id, # ID of the user message that triggered this AI response
                "category": typing_category, # Send category instead of mate_name
                "model_name": model_name, # Add model_name to the payload
                "provider_name": provider_name, # Add provider_name to the payload
                "server_region": server_region, # Add server region to the payload (e.g., "EU", "US", "APAC")
                # CRITICAL: Include is_continuation flag so client knows to skip re-persisting the user message
                # When this is True, the user message was already persisted before the app settings/memories
                # or focus mode deferred activation pause
                "is_continuation": request_data.is_app_settings_memories_continuation or request_data.is_focus_mode_continuation,
            }
            
            # Log the complete typing payload for debugging
            logger.info(f"[Task ID: {task_id}] Typing payload BEFORE adding title/icon: category={typing_category}, model_name={model_name}, provider_name={provider_name}, server_region={server_region}")
            
            # Only add title and icon_names if they were generated (new chat only)
            # If chat already has a title, preprocessing skips generation of these fields
            # CRITICAL: title and icon_names should ONLY be sent together (both or neither)
            # This ensures metadata is only set once during the first message
            if preprocessing_result.title and preprocessing_result.icon_names:
                # NEW CHAT ONLY - both title and icon_names must be present
                typing_payload_data["title"] = preprocessing_result.title
                typing_payload_data["icon_names"] = preprocessing_result.icon_names
                logger.info(f"[Task ID: {task_id}] NEW CHAT: Including title '{preprocessing_result.title}' and icon_names {preprocessing_result.icon_names} in typing event")
            elif preprocessing_result.title or preprocessing_result.icon_names:
                # VALIDATION ERROR: Both should be present or both should be absent
                logger.warning(f"[Task ID: {task_id}] INCONSISTENCY: title={bool(preprocessing_result.title)}, icon_names={bool(preprocessing_result.icon_names)}. Should be both present or both absent. Skipping metadata to avoid partial update.")
            else:
                logger.debug(f"[Task ID: {task_id}] FOLLOW-UP MESSAGE: No title/icon_names generated (chat already has metadata)")
            
            # CRITICAL: Skip WebSocket events for external requests (REST API)
            # This prevents typing indicators from popping up in the web app when a user makes an API call.
            if not request_data.is_external:
                typing_indicator_channel = f"ai_typing_indicator_events::{request_data.user_id_hash}" # Channel uses hashed ID
                await cache_service_instance.publish_event(typing_indicator_channel, typing_payload_data)
                logger.info(f"[Task ID: {task_id}] Published '{typing_payload_data['event_for_client']}' event to Redis channel '{typing_indicator_channel}' with metadata for encryption.")
            else:
                logger.info(f"[Task ID: {task_id}] External request detected. Skipping '{typing_payload_data['event_for_client']}' Redis publish for Web App.")
        except Exception as e_typing_pub:
            event_name_for_log = typing_payload_data.get('event_for_client', 'ai_typing_started') if 'typing_payload_data' in locals() else 'ai_typing_started'
            logger.error(f"[Task ID: {task_id}] Failed to publish event for '{event_name_for_log}' to Redis: {e_typing_pub}", exc_info=True)
    elif not cache_service_instance and preprocessing_result and preprocessing_result.can_proceed: 
        logger.warning(f"[Task ID: {task_id}] Cache service not available. Skipping 'ai_typing_started' Redis publish.")


    # --- Step 2: Main Processing (with streaming) ---
    # Sync wrapper handles Celery state update for progress
    logger.info(f"[Task ID: {task_id}] Starting main processing step (streaming)...")

    # Old debug log for "Main-processing Input (from PreprocessingResult)" is removed.
    # llm_utils.py logs the input to the main processing LLM call.
    
    aggregated_final_response: str = ""
    revoked_in_consumer = False
    soft_limited_in_consumer = False

    try:
        aggregated_final_response, revoked_in_consumer, soft_limited_in_consumer = await _consume_main_processing_stream(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            base_instructions=base_instructions,
            directus_service=directus_service_instance,
            encryption_service=encryption_service_instance,
            user_vault_key_id=user_vault_key_id,
            all_mates_configs=all_mates_configs,
            discovered_apps_metadata=discovered_apps_metadata,
            cache_service=cache_service_instance,
            secrets_manager=secrets_manager,
            # Pass always-include skills from skill config - these skills are ALWAYS available
            # to the main LLM regardless of preprocessing preselection.
            # This is a safety net for critical skills like web-search that should be available
            # for follow-up queries even when preprocessing fails to detect the user's intent.
            always_include_skills=skill_config.always_include_skills if skill_config else None
        )
        logger.info(f"[Task ID: {task_id}] Main processing stream consumed.")

        # --- Cache debug data for main processor stage ---
        # This caches the last 10 requests for debugging purposes (encrypted, 30-minute TTL)
        # IMPORTANT: Store FULL content to enable proper debugging of the AI decision process
        try:
            if cache_service_instance and encryption_service_instance:
                # Safely serialize preprocessing_result to avoid serialization errors
                # Use mode='json' for JSON-safe output, catching any serialization issues
                preprocessing_result_dict = None
                if preprocessing_result:
                    try:
                        preprocessing_result_dict = preprocessing_result.model_dump(mode='json')
                    except Exception as e_serialize:
                        logger.error(f"[Task ID: {task_id}] Failed to serialize preprocessing_result for debug cache: {e_serialize}")
                        # Fallback: try to capture key fields manually
                        preprocessing_result_dict = {
                            "serialization_error": str(e_serialize),
                            "can_proceed": getattr(preprocessing_result, 'can_proceed', None),
                            "category": getattr(preprocessing_result, 'category', None),
                        }
                
                # Prepare main processor input data with FULL preprocessing result
                main_processor_input = {
                    "chat_id": request_data.chat_id,
                    "task_id": task_id,
                    # Full preprocessing result that drives main processor behavior
                    "preprocessing_result": preprocessing_result_dict,
                    # Key fields extracted for quick reference
                    "preprocessing_can_proceed": preprocessing_result.can_proceed if preprocessing_result else None,
                    "preprocessing_selected_model": preprocessing_result.selected_main_llm_model_id if preprocessing_result else None,
                    "preprocessing_category": preprocessing_result.category if preprocessing_result else None,
                    "preprocessing_preselected_skills": preprocessing_result.relevant_app_skills if preprocessing_result else [],
                    "preprocessing_chat_summary": preprocessing_result.chat_summary if preprocessing_result else None,
                    "preprocessing_chat_tags": preprocessing_result.chat_tags if preprocessing_result else [],
                    # Context info
                    "message_history_count": len(request_data.message_history) if request_data.message_history else 0,
                    "discovered_apps_count": len(discovered_apps_metadata) if discovered_apps_metadata else 0,
                    "discovered_app_ids": list(discovered_apps_metadata.keys()) if discovered_apps_metadata else [],
                    "always_include_skills": skill_config.always_include_skills if skill_config else None,
                    "user_vault_key_id": user_vault_key_id,
                    "mates_count": len(all_mates_configs) if all_mates_configs else 0,
                }
                
                # Prepare main processor output data with FULL response
                main_processor_output = {
                    # FULL AI response for debugging
                    "full_response": aggregated_final_response,
                    "response_length": len(aggregated_final_response) if aggregated_final_response else 0,
                    "revoked_in_consumer": revoked_in_consumer,
                    "soft_limited_in_consumer": soft_limited_in_consumer,
                }
                
                await cache_service_instance.cache_debug_request_entry(
                    encryption_service=encryption_service_instance,
                    task_id=task_id,
                    chat_id=request_data.chat_id,
                    user_id=request_data.user_id,
                    stage="main_processor",
                    input_data=main_processor_input,
                    output_data=main_processor_output,
                )
                logger.info(f"[Task ID: {task_id}] Cached main_processor debug data (admin only)")
        except Exception as e_debug:
            # Don't fail the task if debug caching fails - log at ERROR level with full traceback
            logger.error(f"[Task ID: {task_id}] Failed to cache main_processor debug data (non-fatal): {e_debug}", exc_info=True)

        # Sync wrapper handles Celery state update for progress
        task_was_revoked = revoked_in_consumer # Update overall flag
        task_was_soft_limited = soft_limited_in_consumer # Update overall flag

    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded during task execution (around _consume_main_processing_stream call).")
        task_was_soft_limited = True # Set overall flag
        raise # Re-raise for sync wrapper to handle Celery state
    except Exception as e:
        # Check for revocation if an unexpected error occurs
        # Use .state == 'REVOKED' for checking revocation status
        if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
            logger.warning(f"[Task ID: {task_id}] Task revoked during or after main processing stream execution.")
            task_was_revoked = True # Set overall flag
        else:
            logger.error(f"[Task ID: {task_id}] Error during main processing stream execution: {e}", exc_info=True)
        raise RuntimeError(f"Main processing stream execution failed: {e}") # Re-raise for sync wrapper

    # --- Queue Processing (after main processing, before post-processing) ---
    # Process queued messages immediately after main processing completes
    # This allows the next message to start processing while post-processing continues in parallel
    # Post-processing is independent (only generates suggestions) and doesn't conflict with starting new tasks
    if cache_service_instance:
        # Clear the active task marker for this chat
        # This allows new messages to be processed immediately instead of queued
        await cache_service_instance.clear_active_ai_task(request_data.chat_id)
        logger.debug(f"[Task ID: {task_id}] Cleared active AI task marker for chat {request_data.chat_id} after main processing")
        
        # Check for queued messages and process them
        # This implements the queue system: when main processing completes, process any queued messages
        queued_messages = await cache_service_instance.get_queued_messages(request_data.chat_id)
        
        if queued_messages and len(queued_messages) > 0:
            logger.info(f"[Task ID: {task_id}] Found {len(queued_messages)} queued message(s) for chat {request_data.chat_id}. Processing combined message (post-processing will continue in parallel).")
            
            # Combine multiple queued messages into one
            # If user sent "Also explain docker" then "and Ruby", combine to "Also explain docker\n\nand Ruby"
            combined_content_parts = []
            combined_message_ids = []
            combined_user_id = None
            combined_user_id_hash = None
            combined_chat_id = request_data.chat_id
            combined_active_focus_id = None
            combined_chat_has_title = True  # Default to True since we're in an existing chat
            
            # Process each queued message
            for queued_msg in queued_messages:
                # Extract content from the queued message
                # The queued message has the same structure as AskSkillRequest
                if isinstance(queued_msg, dict):
                    msg_content = queued_msg.get("message_history", [])
                    if msg_content and len(msg_content) > 0:
                        # Get the last message (the user's message) from history
                        last_msg = msg_content[-1] if isinstance(msg_content, list) else None
                        if last_msg and isinstance(last_msg, dict):
                            content = last_msg.get("content", "")
                            if content:
                                combined_content_parts.append(content)
                                combined_message_ids.append(queued_msg.get("message_id", ""))
                                
                                # Capture user info from first message
                                if combined_user_id is None:
                                    combined_user_id = queued_msg.get("user_id")
                                    combined_user_id_hash = queued_msg.get("user_id_hash")
                                    combined_active_focus_id = queued_msg.get("active_focus_id")
                                    combined_chat_has_title = queued_msg.get("chat_has_title", True)
            
            if combined_content_parts:
                # Combine messages with double newline separator
                combined_content = "\n\n".join(combined_content_parts)
                
                # Create a new combined message ID (use the first message's ID as base)
                combined_message_id = combined_message_ids[0] if combined_message_ids else f"{combined_chat_id}-{uuid.uuid4()}"
                
                logger.info(f"[Task ID: {task_id}] Combined {len(combined_content_parts)} queued messages into one. Combined content length: {len(combined_content)}")
                
                # Get updated message history including the just-completed AI response
                # This ensures the combined message has full context
                # Start with the original request's message history
                updated_message_history = []
                if request_data.message_history:
                    # Convert AIHistoryMessage objects to dicts for easier manipulation
                    for msg in request_data.message_history:
                        if isinstance(msg, dict):
                            updated_message_history.append(msg)
                        else:
                            # AIHistoryMessage Pydantic model - convert to dict
                            updated_message_history.append({
                                "role": msg.role,
                                "content": msg.content,
                                "created_at": msg.created_at,
                                "sender_name": getattr(msg, 'sender_name', msg.role),
                                "category": getattr(msg, 'category', None)
                            })
                
                # Add the completed AI response to history
                if aggregated_final_response:
                    updated_message_history.append({
                        "role": "assistant",
                        "content": aggregated_final_response,
                        "created_at": int(time.time()),
                        "sender_name": "assistant"
                    })
                
                # Add the combined user message(s) to history
                updated_message_history.append({
                    "role": "user",
                    "content": combined_content,
                    "created_at": int(time.time()),
                    "sender_name": "user"
                })
                
                # Create a new AskSkillRequest for the combined message
                # Import the necessary modules
                from backend.apps.ai.skills.ask_skill import AskSkillRequest as AskSkillRequestType
                from backend.apps.ai.skills.ask_skill import AIHistoryMessage
                
                # Convert dict history back to AIHistoryMessage objects
                history_objects = []
                for msg_dict in updated_message_history:
                    history_objects.append(AIHistoryMessage(
                        role=msg_dict.get("role", "user"),
                        content=msg_dict.get("content", ""),
                        created_at=msg_dict.get("created_at", int(time.time())),
                        sender_name=msg_dict.get("sender_name", msg_dict.get("role", "user")),
                        category=msg_dict.get("category")
                    ))
                
                # Preserve the current task's selected mate for follow-up messages.
                # Without this, the preprocessor would re-select a mate based on category,
                # potentially switching to a different persona mid-conversation.
                current_mate_id = preprocessing_result.selected_mate_id if preprocessing_result else None
                
                combined_request = AskSkillRequestType(
                    chat_id=combined_chat_id,
                    message_id=combined_message_id,
                    user_id=combined_user_id or request_data.user_id,
                    user_id_hash=combined_user_id_hash or request_data.user_id_hash,
                    message_history=history_objects,
                    chat_has_title=combined_chat_has_title,
                    mate_id=current_mate_id,  # Preserve current mate instead of forcing re-selection
                    active_focus_id=combined_active_focus_id or request_data.active_focus_id,
                    user_preferences={}
                )
                
                # Dispatch a new Celery task for the combined queued message
                # This will be processed immediately, while post-processing continues in parallel
                try:
                    # Get skill config (same as original task)
                    skill_config_dict = skill_config.model_dump() if hasattr(skill_config, 'model_dump') else {}
                    
                    # Dispatch new task via Celery
                    new_task_result = celery_config.app.send_task(
                        name='apps.ai.tasks.skill_ask',
                        kwargs={
                            "request_data_dict": combined_request.model_dump(),
                            "skill_config_dict": skill_config_dict
                        },
                        queue='app_ai'
                    )
                    
                    logger.info(f"[Task ID: {task_id}] Dispatched new Celery task {new_task_result.id} for combined queued message(s) in chat {combined_chat_id} (post-processing continues in parallel)")
                    
                    # Mark the new task as active
                    await cache_service_instance.set_active_ai_task(combined_chat_id, new_task_result.id)
                    
                except Exception as e_queue:
                    logger.error(f"[Task ID: {task_id}] Failed to dispatch queued message task: {e_queue}", exc_info=True)
                    # Don't fail the current task if queue processing fails
            else:
                logger.warning(f"[Task ID: {task_id}] Queued messages found but could not extract content for combining")
        else:
            logger.debug(f"[Task ID: {task_id}] No queued messages found for chat {request_data.chat_id}")

    # --- Step 3: Post-Processing (Generate Suggestions and Metadata) ---
    # Post-processing continues even when revoked - we still have a partial response to process
    # Only skip if there's no response content at all.
    # CRITICAL: Skip post-processing for external requests (REST API)
    # External requests only care about the main response content, not suggestions or summary.
    # This also prevents 'post_processing_completed' events from being broadcasted to the web app.
    postprocessing_result: Optional[PostProcessingResult] = None
    if not task_was_soft_limited and aggregated_final_response and not request_data.is_external:
        logger.info(f"[Task ID: {task_id}] Starting post-processing step...")

        # Get the last user message from request_data
        last_user_message = ""
        if request_data.message_history and len(request_data.message_history) > 0:
            # Find the last user message in history
            # Note: message_history contains AIHistoryMessage Pydantic models, not dicts
            for msg in reversed(request_data.message_history):
                if msg.role == "user":
                    last_user_message = msg.content
                    break

        # Get chat summary and tags from preprocessing result (generated from full chat history)
        # CRITICAL: Check if preprocessing failed before accessing fields
        # If preprocessing failed (can_proceed=False or error_message set), chat_summary will be None/empty
        preprocessing_failed = (
            not preprocessing_result 
            or not preprocessing_result.can_proceed 
            or preprocessing_result.error_message is not None
        )
        
        chat_summary = preprocessing_result.chat_summary if preprocessing_result and not preprocessing_failed else None
        chat_tags = preprocessing_result.chat_tags if preprocessing_result and not preprocessing_failed else []

        # Extract available app IDs from discovered_apps_metadata for post-processing validation
        # NOTE: This must be defined before the preprocessing_failed branch, because
        # the debug caching code below references it regardless of which branch is taken.
        available_app_ids = list(discovered_apps_metadata.keys()) if discovered_apps_metadata else []

        # CRITICAL: chat_summary is required for post-processing
        # If missing, log detailed information to understand why the preprocessing LLM didn't return it
        if preprocessing_failed or not chat_summary:
            # Determine the specific reason for failure
            if preprocessing_failed:
                failure_reason = (
                    preprocessing_result.error_message 
                    if preprocessing_result and preprocessing_result.error_message 
                    else "Preprocessing failed (can_proceed=False)"
                )
                logger.error(
                    f"[Task ID: {task_id}] CRITICAL: Preprocessing failed - cannot generate suggestions. "
                    f"Failure reason: {failure_reason}. "
                    f"Preprocessing result available: {preprocessing_result is not None}. "
                    f"Can proceed: {preprocessing_result.can_proceed if preprocessing_result else 'N/A'}. "
                    f"Raw LLM response from preprocessing: {preprocessing_result.raw_llm_response if preprocessing_result else 'N/A'}. "
                    f"Chat ID: {request_data.chat_id}. "
                    f"Message ID: {request_data.message_id}. "
                    f"Message history length: {len(request_data.message_history) if request_data.message_history else 0}. "
                    f"This indicates the preprocessing LLM call failed or returned an error."
                )
            else:
                logger.error(
                    f"[Task ID: {task_id}] CRITICAL: Chat summary not available from preprocessing - cannot generate suggestions. "
                    f"This indicates the preprocessing LLM failed to return a required field. "
                    f"Preprocessing result available: {preprocessing_result is not None}. "
                    f"Preprocessing result keys: {list(preprocessing_result.model_dump().keys()) if preprocessing_result else 'N/A'}. "
                    f"Raw LLM response from preprocessing: {preprocessing_result.raw_llm_response if preprocessing_result else 'N/A'}. "
                    f"Chat ID: {request_data.chat_id}. "
                    f"Message ID: {request_data.message_id}. "
                    f"Message history length: {len(request_data.message_history) if request_data.message_history else 0}. "
                    f"This is a critical error that needs investigation - the preprocessing LLM should always return chat_summary."
                )
            # Skip post-processing but log the error for debugging
            postprocessing_result = None
        else:
            if not available_app_ids:
                logger.warning(f"[Task ID: {task_id}] No available app IDs found in discovered_apps_metadata for post-processing validation")

            # Extract settings/memory categories for Phase 1 (lightweight category selection)
            available_settings_memory_categories = extract_settings_memory_categories(
                discovered_apps_metadata
            ) if discovered_apps_metadata else []
            logger.debug(f"[Task ID: {task_id}] Extracted {len(available_settings_memory_categories)} settings/memory categories for post-processing")

            # Build full message history for post-processing (same format as preprocessing)
            # This allows post-processing to generate summaries from the full chat history
            # instead of relying on a condensed 20-word summary from preprocessing
            postprocessing_message_history = []
            if request_data.message_history:
                postprocessing_message_history = [
                    msg.model_dump() if hasattr(msg, 'model_dump') else msg
                    for msg in request_data.message_history
                ]

            # Extract language info for suggestion generation:
            # - output_language: the conversation/chat language detected by preprocessor (for follow-up suggestions)
            # - user_system_language: the user's UI/system language from their profile (for new chat suggestions)
            # This ensures new chat suggestions are always in the user's system language,
            # preventing a mixed-language welcome screen for multilingual users.
            chat_output_language = preprocessing_result.output_language if preprocessing_result else "en"
            user_system_language = request_data.user_preferences.get("language", "en") if request_data.user_preferences else "en"

            # Phase 1: Post-processing with category selection
            postprocessing_result = await handle_postprocessing(
                task_id=task_id,
                user_message=last_user_message,
                assistant_response=aggregated_final_response,
                chat_summary=chat_summary,
                chat_tags=chat_tags,
                message_history=postprocessing_message_history,
                base_instructions=base_instructions,
                secrets_manager=secrets_manager,
                cache_service=cache_service_instance,
                available_app_ids=available_app_ids,
                available_settings_memory_categories=available_settings_memory_categories,
                is_incognito=getattr(request_data, 'is_incognito', False),  # Pass incognito flag
                output_language=chat_output_language,
                user_system_language=user_system_language,
            )

            # Phase 2: Memory generation (only if Phase 1 identified relevant categories)
            if (postprocessing_result 
                and postprocessing_result.relevant_settings_memory_categories 
                and discovered_apps_metadata):
                
                logger.info(f"[Task ID: {task_id}] Phase 2: Generating memory entries for categories: {postprocessing_result.relevant_settings_memory_categories}")
                
                # Get full schemas for the selected categories
                category_schemas = get_category_schemas(
                    discovered_apps_metadata,
                    postprocessing_result.relevant_settings_memory_categories
                )
                
                if category_schemas:
                    # Generate actual entry suggestions
                    suggested_entries = await handle_memory_generation(
                        task_id=task_id,
                        user_message=last_user_message,
                        assistant_response=aggregated_final_response,
                        relevant_categories=postprocessing_result.relevant_settings_memory_categories,
                        category_schemas=category_schemas,
                        base_instructions=base_instructions,
                        secrets_manager=secrets_manager,
                    )
                    
                    # Update the postprocessing result with generated entries
                    postprocessing_result.suggested_settings_memories = suggested_entries
                    logger.info(f"[Task ID: {task_id}] Phase 2 complete: Generated {len(suggested_entries)} memory entry suggestions")
                else:
                    logger.warning(f"[Task ID: {task_id}] Phase 2 skipped: No schemas found for selected categories")

        if postprocessing_result and cache_service_instance:
            # Publish post-processing results to Redis for WebSocket delivery to client
            # Client will encrypt with chat-specific key and sync back to Directus
            # chat_summary: prefer post-processing version (includes latest exchange) over preprocessing
            # chat_tags: from preprocessing (full history context)
            final_chat_summary = postprocessing_result.chat_summary or chat_summary
            if postprocessing_result.chat_summary:
                logger.info(f"[Task ID: {task_id}] Using post-processing chat_summary (length: {len(postprocessing_result.chat_summary)})")
            else:
                logger.info(f"[Task ID: {task_id}] Falling back to preprocessing chat_summary (post-processing didn't provide one)")
            # Convert suggested_settings_memories to serializable format
            suggested_settings_memories_serialized = [
                entry.model_dump() for entry in postprocessing_result.suggested_settings_memories
            ] if postprocessing_result.suggested_settings_memories else []
            
            postprocessing_payload = {
                "type": "post_processing_completed",
                "event_for_client": "post_processing_completed",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "user_id_uuid": request_data.user_id,
                "user_id_hash": request_data.user_id_hash,
                "follow_up_request_suggestions": postprocessing_result.follow_up_request_suggestions,
                "new_chat_request_suggestions": postprocessing_result.new_chat_request_suggestions,
                "chat_summary": final_chat_summary,  # Prefer post-processing summary (includes latest exchange), fall back to preprocessing
                "chat_tags": chat_tags,  # From preprocessing (full history context)
                "harmful_response": postprocessing_result.harmful_response,
                "top_recommended_apps_for_user": postprocessing_result.top_recommended_apps_for_user,
                # Phase 2: Suggested settings/memories entries (sent as plaintext, client encrypts)
                "suggested_settings_memories": suggested_settings_memories_serialized,
            }

            postprocessing_channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
            await cache_service_instance.publish_event(postprocessing_channel, postprocessing_payload)
            logger.info(f"[Task ID: {task_id}] Published post-processing results to Redis channel '{postprocessing_channel}'")

        # --- Cache debug data for postprocessor stage ---
        # This caches the last 10 requests for debugging purposes (encrypted, 30-minute TTL)
        # IMPORTANT: Store FULL content to enable proper debugging of the AI decision process
        try:
            if cache_service_instance and encryption_service_instance:
                # Prepare postprocessor input data with FULL content
                postprocessor_input = {
                    "chat_id": request_data.chat_id,
                    "task_id": task_id,
                    # FULL user message that was processed
                    "last_user_message": last_user_message,
                    "last_user_message_length": len(last_user_message) if last_user_message else 0,
                    # FULL assistant response that was generated
                    "assistant_response": aggregated_final_response,
                    "assistant_response_length": len(aggregated_final_response) if aggregated_final_response else 0,
                    # Chat summary: prefer post-processing (includes latest exchange), fall back to preprocessing
                    "chat_summary": final_chat_summary if postprocessing_result else chat_summary,
                    "chat_summary_length": len(final_chat_summary) if (postprocessing_result and final_chat_summary) else (len(chat_summary) if chat_summary else 0),
                    "chat_summary_source": "post-processing" if (postprocessing_result and postprocessing_result.chat_summary) else "preprocessing",
                    # Chat tags from preprocessing
                    "chat_tags": chat_tags,
                    # Available apps for recommendations
                    "available_app_ids": available_app_ids,
                    "available_app_ids_count": len(available_app_ids) if available_app_ids else 0,
                    "is_incognito": getattr(request_data, 'is_incognito', False),
                }
                
                # Prepare postprocessor output data (full model dump)
                postprocessor_output = postprocessing_result.model_dump() if postprocessing_result else None
                
                await cache_service_instance.cache_debug_request_entry(
                    encryption_service=encryption_service_instance,
                    task_id=task_id,
                    chat_id=request_data.chat_id,
                    user_id=request_data.user_id,
                    stage="postprocessor",
                    input_data=postprocessor_input,
                    output_data=postprocessor_output,
                )
                logger.debug(f"[Task ID: {task_id}] Cached postprocessor debug data (admin only)")
        except Exception as e_debug:
            # Don't fail the task if debug caching fails - just log the error
            logger.warning(f"[Task ID: {task_id}] Failed to cache postprocessor debug data (non-fatal): {e_debug}")

            logger.info(f"[Task ID: {task_id}] Post-processing step completed.")
    else:
        reason = "request is external" if request_data.is_external else "no response content or soft-limited"
        logger.info(f"[Task ID: {task_id}] Skipping post-processing (reason: {reason}, task_was_soft_limited={task_was_soft_limited}, has_response={bool(aggregated_final_response)})")

    # Determine final status based on local flags
    final_status_message = "completed"
    log_final_status = "successfully"

    if task_was_soft_limited: # Use local flag
        final_status_message = "completed_partially_soft_limit"
        log_final_status = "partially completed (interrupted by soft time limit)"
    # Check task_was_revoked AFTER soft_limited, as revocation might occur during soft limit handling
    if task_was_revoked: # Use local flag (also check if AsyncResult says so, though flag should capture it)
        final_status_message = "completed_partially_revoked"
        log_final_status = "partially completed (interrupted by revocation)"

    logger.info(f"[Task ID: {task_id}] AI skill ask task processing finished {log_final_status}.")

    return {
        "task_id": task_id,
        "status": final_status_message,
        "preprocessing_summary": preprocessing_result.model_dump() if preprocessing_result else {},
        "main_processing_output": aggregated_final_response,
        "postprocessing_summary": postprocessing_result.model_dump() if postprocessing_result else {},
        "interrupted_by_soft_time_limit": task_was_soft_limited, # Return determined flag
        "interrupted_by_revocation": task_was_revoked, # Return determined flag
        "_celery_task_state": "SUCCESS"
    }


@celery_config.app.task(
    bind=True, 
    name="apps.ai.tasks.skill_ask", 
    soft_time_limit=300, 
    time_limit=360,
    autoretry_for=(ChatNotFoundError,),
    retry_kwargs={'max_retries': 3},
    retry_backoff=False,
    retry_jitter=False,
    countdown=1
)
def process_ai_skill_ask_task(self, request_data_dict: dict, skill_config_dict: dict):
    task_id = self.request.id
    # Conditionally log request and skill config data based on environment
    # Even in development, we sanitize sensitive data (message_history, chat_tags, chat_summary, etc.)
    # to show only counts and lengths, not actual content
    if os.getenv("SERVER_ENVIRONMENT", "development") != "production":
        # Sanitize request data to show only metadata (counts, lengths) instead of actual content
        sanitized_request = sanitize_request_data_for_logging(request_data_dict)
        logger.info(f"[Task ID: {task_id}] Received apps.ai.tasks.skill_ask task. Request: {sanitized_request}, Skill Config: {skill_config_dict}")
    else:
        # In production, never log request data with sensitive content
        logger.info(f"[Task ID: {task_id}] Received apps.ai.tasks.skill_ask task.")

    # Custom flags on 'self' are no longer initialized here,
    # their status will be derived from the async helper's return value.

    try:
        request_data = AskSkillRequest(**request_data_dict)
        skill_config = AskSkillDefaultConfig(**skill_config_dict)
    except ValidationError as e:
        logger.error(f"[Task ID: {task_id}] Validation error for input data: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': 'ValidationError', 'exc_message': str(e.errors())})
        raise Ignore()

    # Focus mode continuation now creates its own assistant message (this task_id).
    # Client merges "focus activation" + "continuation" into one bubble for display.

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    task_result_dict: Optional[Dict[str, Any]] = None
    try:
        # Update progress before calling async helper
        self.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'started'})

        task_result_dict = loop.run_until_complete(
            _async_process_ai_skill_ask_task(task_id, request_data, skill_config) # 'self' is not passed
        )
        
        # Update progress after preprocessing if successful and before main processing (if applicable)
        # The async helper now returns more detailed status, so we use that.
        if task_result_dict and task_result_dict.get("preprocessing_summary"):
             self.update_state(state='PROGRESS', meta={
                 'step': 'preprocessing', 'status': 'completed', 
                 'result': task_result_dict.get("preprocessing_summary")
            })
        
        if task_result_dict and task_result_dict.get("main_processing_output") is not None: # Check if main processing happened
            self.update_state(state='PROGRESS', meta={
                'step': 'main_processing', 'status': 'started_streaming' 
                # Note: 'completed_streaming' status update would happen based on task_result_dict.status
            })


        # Handle results that indicate logical failure within the async logic
        if isinstance(task_result_dict, dict) and task_result_dict.get("_celery_task_state") == "FAILURE":
            failure_meta = {k: v for k, v in task_result_dict.items() if k not in ["_celery_task_state", "task_id"]}
            failure_meta['exc_type'] = str(task_result_dict.get('reason', 'AsyncLogicError'))
            failure_meta['exc_message'] = str(task_result_dict.get('message', 'Async task indicated failure.'))
            # Add interruption flags from async result to the meta
            failure_meta['interrupted_by_soft_time_limit'] = task_result_dict.get('interrupted_by_soft_time_limit', False)
            failure_meta['interrupted_by_revocation'] = task_result_dict.get('interrupted_by_revocation', False)
            self.update_state(state='FAILURE', meta=failure_meta)
            return task_result_dict
        
        # If successful or partially successful (due to interruption)
        if isinstance(task_result_dict, dict):
            success_meta = {
                'status_message': task_result_dict.get('status'),
                'preprocessing_summary': task_result_dict.get('preprocessing_summary'),
                'main_processing_output_summary': (task_result_dict.get('main_processing_output')[:500] + "...") if task_result_dict.get('main_processing_output') and len(task_result_dict.get('main_processing_output')) > 500 else task_result_dict.get('main_processing_output'),
                'interrupted_by_soft_time_limit': task_result_dict.get('interrupted_by_soft_time_limit'),
                'interrupted_by_revocation': task_result_dict.get('interrupted_by_revocation')
            }
            # If task was interrupted, it's technically a failure for Celery unless handled as a custom success state.
            # For now, let's align with Celery's expectation: SUCCESS means fully completed.
            # Partial completions due to limits/revocation are often marked as FAILURE with details.
            current_celery_state = 'SUCCESS'
            if task_result_dict.get('interrupted_by_soft_time_limit') or task_result_dict.get('interrupted_by_revocation'):
                 # Or a custom state if your system handles it, e.g., 'PARTIAL_SUCCESS'
                 # For standard Celery, this might still be 'FAILURE' to prevent retries if not desired.
                 # Let's assume for now that "completed_partially_..." means the task did what it could.
                 # If these should be hard failures, change current_celery_state to 'FAILURE'.
                 pass # Keep as SUCCESS but with interruption flags in meta.

            self.update_state(state=current_celery_state, meta=success_meta)
            return task_result_dict
        else: # Should not happen if _async_process_ai_skill_ask_task always returns a dict
            logger.error(f"[Task ID: {task_id}] Async helper returned unexpected type: {type(task_result_dict)}")
            self.update_state(state='FAILURE', meta={'exc_type': 'InternalError', 'exc_message': 'Async helper returned non-dict result.'})
            raise Ignore()


    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded in synchronous task wrapper.")
        # Check if the task was revoked (user-initiated cancellation) to use appropriate embed status
        was_revoked = self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        # CRITICAL: Clean up active_ai_task marker and processing embeds before failing
        # This ensures the typing indicator stops and embeds don't get stuck in "processing" state
        try:
            loop.run_until_complete(_cleanup_on_task_failure(
                task_id=task_id,
                chat_id=request_data.chat_id,
                message_id=request_data.message_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=f"user:{request_data.user_id}:encryption_key",
                error_message="Task exceeded soft time limit",
                use_cancelled_status=bool(was_revoked)
            ))
        except Exception as cleanup_err:
            logger.error(f"[Task ID: {task_id}] Error cleaning up after soft time limit: {cleanup_err}")
        self.update_state(state='FAILURE', meta={
            'exc_type': 'SoftTimeLimitExceeded', 
            'exc_message': 'Task exceeded soft time limit in sync wrapper.',
            'status_message': 'completed_partially_soft_limit_wrapper', # Distinguish from async limit
            'interrupted_by_soft_time_limit': True, # This limit was in the sync part
            'interrupted_by_revocation': bool(was_revoked)
        })
        raise
    except RuntimeError as e: 
        logger.error(f"[Task ID: {task_id}] Runtime error from async task execution: {e}", exc_info=True)
        # Check if the task was revoked (user-initiated cancellation) to use appropriate embed status
        was_revoked = self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        # CRITICAL: Clean up active_ai_task marker and processing embeds before failing
        # This ensures the typing indicator stops and embeds don't get stuck in "processing" state
        try:
            loop.run_until_complete(_cleanup_on_task_failure(
                task_id=task_id,
                chat_id=request_data.chat_id,
                message_id=request_data.message_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=f"user:{request_data.user_id}:encryption_key",
                error_message=str(e),
                use_cancelled_status=bool(was_revoked)
            ))
        except Exception as cleanup_err:
            logger.error(f"[Task ID: {task_id}] Error cleaning up after RuntimeError: {cleanup_err}")
        self.update_state(state='FAILURE', meta={
            'exc_type': 'RuntimeErrorFromAsync', 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False, # Assuming not a soft limit unless explicitly caught as such
            'interrupted_by_revocation': bool(was_revoked)
        })
        raise Ignore()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Unhandled exception in synchronous task wrapper: {e}", exc_info=True)
        # Check if the task was revoked (user-initiated cancellation) to use appropriate embed status
        was_revoked = self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        # CRITICAL: Clean up active_ai_task marker and processing embeds before failing
        # This ensures the typing indicator stops and embeds don't get stuck in "processing" state
        try:
            loop.run_until_complete(_cleanup_on_task_failure(
                task_id=task_id,
                chat_id=request_data.chat_id,
                message_id=request_data.message_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=f"user:{request_data.user_id}:encryption_key",
                error_message=str(e),
                use_cancelled_status=bool(was_revoked)
            ))
        except Exception as cleanup_err:
            logger.error(f"[Task ID: {task_id}] Error cleaning up after exception: {cleanup_err}")
        self.update_state(state='FAILURE', meta={
            'exc_type': str(type(e).__name__), 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False,
            'interrupted_by_revocation': bool(was_revoked)
            })
        raise Ignore()
    finally:
        loop.close()
        logger.info(f"[Task ID: {task_id}] Async event loop closed.")
