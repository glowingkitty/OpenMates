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
import hashlib
import uuid
from typing import Dict, Any, List, Optional
import json
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
from backend.apps.ai.processing.postprocessor import handle_postprocessing, PostProcessingResult
from .stream_consumer import _consume_main_processing_stream


logger = logging.getLogger(__name__)

# Note: Avoid internal API lookups per task to keep latency low. We rely on
# the worker-local ConfigManager (see celery_config) and fail fast if configs are missing.

# Internal API configuration for fallback cache refresh
# This is used when discovered_apps_metadata is missing from cache (e.g., cache expired or flushed)
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
INTERNAL_API_TIMEOUT = 10.0  # Timeout for internal API requests in seconds


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
    secrets_manager = None
    cache_service_instance = None
    directus_service_instance = None
    encryption_service_instance = None

    try:
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        logger.info(f"[Task ID: {task_id}] SecretsManager initialized.")

        cache_service_instance = CacheService()
        await cache_service_instance.client 
        logger.info(f"[Task ID: {task_id}] CacheService initialized.")
        
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
        # The synchronous wrapper will handle updating Celery state.
        # We raise RuntimeError to signal failure to the sync wrapper.
        # The sync wrapper will call self.update_state.
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

    # --- Fetch user_vault_key_id from cache and user_app_memories_metadata from Directus ---
    user_vault_key_id: Optional[str] = None
    if cache_service_instance and request_data.user_id:
        cached_user_data = await cache_service_instance.get_user_by_id(request_data.user_id)
        if not cached_user_data:
            logger.error(f"[Task ID: {task_id}] Failed to retrieve cached user data for user_id: {request_data.user_id}. Aborting task.")
            raise RuntimeError("User data not found in cache.")

        user_vault_key_id = cached_user_data.get("vault_key_id")
        if not user_vault_key_id:
            logger.error(f"[Task ID: {task_id}] vault_key_id not found in cached user data for user_id: {request_data.user_id}. Aborting task.")
            raise RuntimeError("User vault key ID not found in cache.")
        logger.info(f"[Task ID: {task_id}] Successfully retrieved user_vault_key_id from cache using user_id: {request_data.user_id}.")
    elif not cache_service_instance:
        logger.error(f"[Task ID: {task_id}] CacheService instance not available. Cannot fetch user_vault_key_id. Aborting task.")
        raise RuntimeError("CacheService not available.")
    elif not request_data.user_id:
        logger.error(f"[Task ID: {task_id}] user_id is missing in request_data. Cannot fetch user_vault_key_id. Aborting task.")
        raise RuntimeError("user_id is missing.")

    user_app_memories_metadata: Dict[str, List[str]] = {}
    # TODO: [v0.2] Re-enable this functionality with client-side E2EE.
    # The current implementation is disabled to prevent errors and will be replaced.
    # if directus_service_instance and request_data.user_id_hash:
    #     try:
    #         raw_items_metadata: List[Dict[str, Any]] = await directus_service_instance.app_settings_and_memories.get_user_app_data_metadata(request_data.user_id_hash)
    #         for item_meta in raw_items_metadata:
    #             app_id_key = item_meta.get("app_id")
    #             item_key_val = item_meta.get("item_key")
    #             if app_id_key and item_key_val:
    #                 if app_id_key not in user_app_memories_metadata:
    #                     user_app_memories_metadata[app_id_key] = []
    #                 if item_key_val not in user_app_memories_metadata[app_id_key]:
    #                     user_app_memories_metadata[app_id_key].append(item_key_val)
    #         logger.info(f"[Task ID: {task_id}] Successfully fetched user_app_memories_metadata (keys) from Directus.")
    #     except Exception as e:
    #         logger.error(f"[Task ID: {task_id}] Error during Directus ops for fetching user_app_memories_metadata: {e}", exc_info=True)
    # elif not directus_service_instance:
    #     logger.warning(f"[Task ID: {task_id}] DirectusService not available. Cannot fetch user app memories metadata.")

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
            discovered_apps_metadata=discovered_apps_metadata  # Pass discovered apps for tool preselection
        )

        # Note: We no longer handle harmful content rejection here.
        # Instead, we let it flow through to the stream consumer which will handle it properly
        # with the normal streaming flow, ensuring the frontend gets proper completion signals.
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error during preprocessing: {e}", exc_info=True)
        raise RuntimeError(f"Preprocessing failed: {e}")

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
    # Note: We now send typing indicator for both successful and harmful content cases
    # since harmful content gets processed through the stream consumer with a predefined response
    if preprocessing_result and cache_service_instance:
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
                                                logger.debug(f"[Task ID: {task_id}] Server match found! Server name from config: '{provider_name}'")
                                                if not provider_name:
                                                    # Server name not set, use capitalized server ID
                                                    provider_name = default_server_id.capitalize()
                                                    logger.warning(f"[Task ID: {task_id}] Server '{default_server_id}' found but has no 'name' field, using capitalized ID '{provider_name}'")
                                                else:
                                                    logger.info(f"[Task ID: {task_id}] ✅ Successfully extracted server name '{provider_name}' for default_server '{default_server_id}' in model '{model_id}'")
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
            
            # Log the final provider name that will be sent to client
            logger.info(f"[Task ID: {task_id}] Provider name to send to client: '{provider_name}'")
            
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
            }
            
            # Log the complete typing payload for debugging
            logger.info(f"[Task ID: {task_id}] Typing payload BEFORE adding title/icon: category={typing_category}, model_name={model_name}, provider_name={provider_name}")
            
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
            typing_indicator_channel = f"ai_typing_indicator_events::{request_data.user_id_hash}" # Channel uses hashed ID
            await cache_service_instance.publish_event(typing_indicator_channel, typing_payload_data)
            logger.info(f"[Task ID: {task_id}] Published '{typing_payload_data['event_for_client']}' event to Redis channel '{typing_indicator_channel}' with metadata for encryption.")
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
                
                combined_request = AskSkillRequestType(
                    chat_id=combined_chat_id,
                    message_id=combined_message_id,
                    user_id=combined_user_id or request_data.user_id,
                    user_id_hash=combined_user_id_hash or request_data.user_id_hash,
                    message_history=history_objects,
                    chat_has_title=combined_chat_has_title,
                    mate_id=None,
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
    # Only skip if there's no response content at all
    postprocessing_result: Optional[PostProcessingResult] = None
    if not task_was_soft_limited and aggregated_final_response:
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
            # Extract available app IDs from discovered_apps_metadata for post-processing validation
            available_app_ids = list(discovered_apps_metadata.keys()) if discovered_apps_metadata else []
            if not available_app_ids:
                logger.warning(f"[Task ID: {task_id}] No available app IDs found in discovered_apps_metadata for post-processing validation")

            postprocessing_result = await handle_postprocessing(
                task_id=task_id,
                user_message=last_user_message,
                assistant_response=aggregated_final_response,
                chat_summary=chat_summary,
                chat_tags=chat_tags,
                base_instructions=base_instructions,
                secrets_manager=secrets_manager,
                cache_service=cache_service_instance,
                available_app_ids=available_app_ids,
                is_incognito=getattr(request_data, 'is_incognito', False),  # Pass incognito flag
            )

        if postprocessing_result and cache_service_instance:
            # Publish post-processing results to Redis for WebSocket delivery to client
            # Client will encrypt with chat-specific key and sync back to Directus
            # Note: chat_summary and chat_tags come from preprocessing (full history context)
            # Use the extracted variables (chat_summary, chat_tags) which are safe to use here
            # since we only reach this point if postprocessing_result was successfully created
            postprocessing_payload = {
                "type": "post_processing_completed",
                "event_for_client": "post_processing_completed",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "user_id_uuid": request_data.user_id,
                "user_id_hash": request_data.user_id_hash,
                "follow_up_request_suggestions": postprocessing_result.follow_up_request_suggestions,
                "new_chat_request_suggestions": postprocessing_result.new_chat_request_suggestions,
                "chat_summary": chat_summary,  # From preprocessing (full history) - use extracted variable
                "chat_tags": chat_tags,  # From preprocessing (full history) - use extracted variable
                "harmful_response": postprocessing_result.harmful_response,
                "top_recommended_apps_for_user": postprocessing_result.top_recommended_apps_for_user,
            }

            postprocessing_channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
            await cache_service_instance.publish_event(postprocessing_channel, postprocessing_payload)
            logger.info(f"[Task ID: {task_id}] Published post-processing results to Redis channel '{postprocessing_channel}'")

        logger.info(f"[Task ID: {task_id}] Post-processing step completed.")
    else:
        logger.info(f"[Task ID: {task_id}] Skipping post-processing (task_was_revoked={task_was_revoked}, task_was_soft_limited={task_was_soft_limited}, has_response={bool(aggregated_final_response)})")

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
        self.update_state(state='FAILURE', meta={
            'exc_type': 'SoftTimeLimitExceeded', 
            'exc_message': 'Task exceeded soft time limit in sync wrapper.',
            'status_message': 'completed_partially_soft_limit_wrapper', # Distinguish from async limit
            'interrupted_by_soft_time_limit': True, # This limit was in the sync part
            'interrupted_by_revocation': self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED # Check current status of self
        })
        raise
    except RuntimeError as e: 
        logger.error(f"[Task ID: {task_id}] Runtime error from async task execution: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={
            'exc_type': 'RuntimeErrorFromAsync', 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False, # Assuming not a soft limit unless explicitly caught as such
            'interrupted_by_revocation': self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        })
        raise Ignore()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Unhandled exception in synchronous task wrapper: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={
            'exc_type': str(type(e).__name__), 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False,
            'interrupted_by_revocation': self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
            })
        raise Ignore()
    finally:
        loop.close()
        logger.info(f"[Task ID: {task_id}] Async event loop closed.")
