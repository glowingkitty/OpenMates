import logging
import os
import redis # Sync redis client for scan_iter and ttl
import json
from celery import shared_task, Celery # Import Celery for beat_schedule
from app.tasks.celery_config import celery_app
from app.services.directus import chat_methods
from app.services.directus.directus import DirectusService # Import DirectusService class directly
from app.services.cache import CacheService
from app.schemas.chat import ChatInDB, CachedChatVersions, CachedChatListItemData
import asyncio
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Sync Redis client for periodic task scanning
REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://cache:6379/0')
# Ensure DRAGONFLY_PASSWORD is used if set for the sync client as well
DRAGONFLY_PASSWORD = os.getenv("DRAGONFLY_PASSWORD", "openmates_cache")

try:
    sync_redis_client = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True, password=DRAGONFLY_PASSWORD)
    sync_redis_client.ping() # Test connection
    logger.info("Successfully connected sync_redis_client for cache_eviction task.")
except redis.exceptions.AuthenticationError as e:
    logger.error(f"AuthenticationError connecting sync_redis_client: {e}. Check DRAGONFLY_PASSWORD.")
    sync_redis_client = None # Set to None if connection fails
except Exception as e:
    logger.error(f"Failed to connect sync_redis_client: {e}")
    sync_redis_client = None


# Configuration for periodic draft persistence
DRAFT_PERSISTENCE_SCAN_INTERVAL_SECONDS = int(os.getenv("DRAFT_PERSISTENCE_SCAN_INTERVAL_SECONDS", 15 * 60)) # e.g., 15 minutes
DRAFT_PERSISTENCE_TTL_WARNING_WINDOW_SECONDS = int(os.getenv("DRAFT_PERSISTENCE_TTL_WARNING_WINDOW_SECONDS", 5 * 60)) # e.g., 5 minutes

# # --- Old Key Prefixes and Helper Functions (Commented out as they are based on old cache structure) ---
# DRAFT_KEY_PREFIX = "draft:"
# CHAT_LIST_META_KEY_PREFIX = "chat_list_meta:"
#
# def is_draft_only_chat_key(key: str) -> bool:
#     return key.startswith(DRAFT_KEY_PREFIX)
#
# def extract_chat_id_from_key(key: str) -> str:
#     return key[len(DRAFT_KEY_PREFIX):]
#
# def fetch_draft_content(chat_id: str) -> dict: ...
# def fetch_chat_metadata(chat_id: str) -> dict: ...

# --- Old listen_for_expiry_events task (Commented out) ---
# This task is reactive. The new requirement is a proactive periodic scan for drafts.
# @celery_app.task(name="cache_eviction.listen_for_expiry_events", bind=True)
# def listen_for_expiry_events(self): ...
# async def handle_draft_eviction(chat_id: str, chat_metadata: dict, draft_data: dict): ...


@celery_app.task(name="cache_eviction.persist_draft_to_directus")
async def persist_draft_to_directus_task(user_id: str, chat_id: str, encrypted_draft_json: Optional[str], cached_draft_version: int):
    """
    Persists a specific chat's draft to Directus.
    """
    logger.info(f"Task persist_draft_to_directus_task: Persisting draft for chat {chat_id} (user: {user_id}), version: {cached_draft_version}")
    directus_service = DirectusService()
    await directus_service.ensure_auth_token()
    
    update_payload = {
        "draft_content": encrypted_draft_json, # This is the field name in Directus chats.yml
        "draft_version_db": cached_draft_version,
        "updated_at": datetime.now(timezone.utc).isoformat() # Ensure ISO format with timezone
    }
    
    try:
        # We need a method in chat_methods to update these specific fields.
        # For now, assuming a generic update method or direct item update.
        # This might be: await directus_service.items("chats").update_one(chat_id, update_payload)
        # Or a more specific method:
        updated = await chat_methods.update_chat_fields_in_directus(
            directus_service=directus_service,
            chat_id=chat_id,
            fields_to_update=update_payload
        )
        if updated:
            logger.info(f"Successfully persisted draft for chat {chat_id} to Directus. New draft_version_db: {cached_draft_version}")
        else:
            logger.error(f"Failed to persist draft for chat {chat_id} to Directus. Update operation returned false.")
    except Exception as e:
        logger.error(f"Error in persist_draft_to_directus_task for chat {chat_id}: {e}", exc_info=True)
        # Optionally, re-raise to let Celery handle retries if configured
        # raise


@celery_app.task(name="cache_eviction.periodic_draft_persistence_scan", bind=True)
def periodic_draft_persistence_scan(self):
    """
    Periodically scans cache for drafts nearing TTL expiry and persists them if newer than DB version.
    This task is intended to be scheduled by Celery Beat.
    """
    if not sync_redis_client:
        logger.error("Periodic draft persistence scan: Sync Redis client not available. Skipping scan.")
        return

    logger.info("Periodic draft persistence scan: Starting scan...")
    cache_service = CacheService() # Instantiate for async methods

    # Pattern for list_item_data keys: user:{user_id}:chat:{chat_id}:list_item_data
    # CacheService defines CHAT_LIST_ITEM_DATA_TTL
    # We need to iterate through all users, then their chats.
    # A more efficient scan pattern might be "user:*:chat:*:list_item_data"
    
    processed_keys = 0
    tasks_dispatched = 0

    try:
        for key in sync_redis_client.scan_iter(match="user:*:chat:*:list_item_data", count=100): # count for batching
            processed_keys += 1
            try:
                key_parts = key.split(':')
                if len(key_parts) != 5:
                    logger.warning(f"Skipping malformed key: {key}")
                    continue
                
                user_id = key_parts[1]
                chat_id = key_parts[3]

                key_ttl = sync_redis_client.ttl(key)
                if key_ttl is None or key_ttl == -1 or key_ttl == -2: # Key has no TTL or does not exist (should not happen with scan_iter)
                    logger.debug(f"Key {key} has no TTL or does not exist. Skipping.")
                    continue

                # Check if TTL is within the warning window
                # CacheService.CHAT_LIST_ITEM_DATA_TTL is the original TTL
                # We want to catch it if current TTL < DRAFT_PERSISTENCE_TTL_WARNING_WINDOW_SECONDS
                if key_ttl <= DRAFT_PERSISTENCE_TTL_WARNING_WINDOW_SECONDS:
                    logger.info(f"Key {key} (user: {user_id}, chat: {chat_id}) is approaching TTL expiry ({key_ttl}s left). Checking draft version.")

                    # Fetch cached versions (async)
                    cached_versions: Optional[CachedChatVersions] = asyncio.run(
                        cache_service.get_chat_versions(user_id, chat_id)
                    )
                    if not cached_versions or cached_versions.draft_v is None:
                        logger.warning(f"Could not get cached draft version for chat {chat_id} (user: {user_id}). Skipping.")
                        continue
                    
                    # Fetch draft_version_db from Directus (async)
                    # This requires DirectusService and a method in chat_methods
                    directus_service_instance = DirectusService() # Create a new instance for this async context
                    asyncio.run(directus_service_instance.ensure_auth_token())
                    chat_data_from_db: Optional[dict] = asyncio.run( # Assuming get_chat_item returns a dict or ChatInDB
                        chat_methods.get_chat_item_from_directus(directus_service_instance, chat_id, fields=["draft_version_db"])
                    )

                    if not chat_data_from_db:
                        logger.warning(f"Chat {chat_id} not found in Directus. Cannot compare draft_version_db. Skipping persistence for now.")
                        # This might mean the chat is new and only in cache, draft persistence might happen on logout/deactivation.
                        continue
                        
                    db_draft_version = chat_data_from_db.get("draft_version_db", 0)

                    if cached_versions.draft_v > db_draft_version:
                        logger.info(f"Cached draft_v ({cached_versions.draft_v}) for chat {chat_id} is newer than DB ({db_draft_version}). Dispatching persistence task.")
                        
                        # Fetch the actual draft content to persist (async)
                        list_item_data: Optional[CachedChatListItemData] = asyncio.run(
                            cache_service.get_chat_list_item_data(user_id, chat_id)
                        )
                        if not list_item_data:
                            logger.error(f"Could not fetch list_item_data for chat {chat_id} (user: {user_id}) even though versions exist. Skipping persistence.")
                            continue

                        # Dispatch the persistence task
                        persist_draft_to_directus_task.delay(
                            user_id=user_id,
                            chat_id=chat_id,
                            encrypted_draft_json=list_item_data.draft_json, # This is already encrypted
                            cached_draft_version=cached_versions.draft_v
                        )
                        tasks_dispatched += 1
                    else:
                        logger.debug(f"Draft for chat {chat_id} (user: {user_id}) is not newer in cache (cache: {cached_versions.draft_v}, db: {db_draft_version}). No persistence needed by periodic scan.")
                else:
                    logger.debug(f"Key {key} TTL ({key_ttl}s) not yet in warning window. Skipping.")

            except Exception as e_inner:
                logger.error(f"Error processing key {key} in periodic scan: {e_inner}", exc_info=True)
                # Continue to next key

    except redis.exceptions.ConnectionError as e_redis:
        logger.error(f"Periodic draft persistence scan: Redis connection error: {e_redis}. Scan aborted.")
    except Exception as e_outer:
        logger.error(f"Unexpected error during periodic draft persistence scan: {e_outer}", exc_info=True)
    
    logger.info(f"Periodic draft persistence scan: Finished. Processed ~{processed_keys} keys. Dispatched {tasks_dispatched} persistence tasks.")


# Configure Celery Beat schedule (this typically goes into celery_config.py or app setup)
# For demonstration, adding it here. In a real setup, this would be part of the Celery app configuration.
# celery_app.conf.beat_schedule = {
#     'periodic-draft-persistence-scan-every-15-minutes': {
#         'task': 'cache_eviction.periodic_draft_persistence_scan',
#         'schedule': DRAFT_PERSISTENCE_SCAN_INTERVAL_SECONDS, # Run every X seconds
#     },
# }
# celery_app.conf.timezone = 'UTC'