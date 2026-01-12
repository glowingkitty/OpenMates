# File: backend/core/api/app/services/directus/app_settings_and_memories_methods.py
# Description: Methods for interacting with the 'user_app_settings_and_memories' collection in Directus.
#
# Field naming conventions:
# - encrypted_item_json: Client-encrypted JSON data (consistent across all code)
# - item_type: Category/type ID for filtering (e.g., 'preferred_technologies', 'watched_movies')
# - item_key: Unique identifier for an entry within a category
# - app_id: The app identifier (e.g., 'code', 'travel', 'tv')

import logging
import hashlib
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .directus import DirectusService # Import for type hinting

logger = logging.getLogger(__name__)

class AppSettingsAndMemoriesMethods:
    """
    Contains methods for interacting with the 'user_app_settings_and_memories' collection in Directus.
    This class replaces the previous AppSettingMethods and AppMemoryMethods.
    
    Directus collection fields:
    - id: UUID primary key (client-generated)
    - hashed_user_id: SHA256 hash of user_id for privacy
    - app_id: App identifier (cleartext for efficient filtering)
    - item_key: Entry identifier within a category
    - item_type: Category/type ID for filtering
    - encrypted_item_json: Client-encrypted JSON data
    - encrypted_app_key: Encrypted app-specific key for device sync
    - created_at, updated_at: Unix timestamps
    - item_version: Version for conflict resolution
    - sequence_number: Optional ordering
    """
    COLLECTION_NAME = "user_app_settings_and_memories"

    def __init__(self, service: 'DirectusService'):
        self._service = service # Store reference to the main DirectusService instance

    def _hash_user_id(self, user_id: str) -> str:
        """Hash user_id for privacy in Directus storage."""
        return hashlib.sha256(user_id.encode()).hexdigest()

    async def get_user_app_item_raw(self, user_id: str, app_id: str, item_key: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a raw user app setting or memory item (including encrypted_item_json)
        for a given user_id, app_id, and item_key.
        Tries cache first, then Directus. Updates cache if fetched from Directus.

        Args:
            user_id: The user's ID (will be hashed for Directus query)
            app_id: The app identifier
            item_key: The item key within the app

        Returns:
            The Directus-like item dictionary if found, else None.
        """
        hashed_user_id = self._hash_user_id(user_id)
        log_prefix = f"AppSettingsAndMemoriesMethods.get_user_app_item_raw (User: {user_id[:8]}..., App: {app_id}, Key: {item_key}):"

        # 1. Try to get from cache
        if self._service.cache_service:
            try:
                cached_encrypted_json = await self._service.cache_service.get_user_app_settings_and_memories_item(
                    user_id_hash=hashed_user_id,
                    app_id=app_id,
                    item_key=item_key
                )
                if cached_encrypted_json is not None: # Can be empty string if that's the stored value
                    logger.info(f"{log_prefix} Cache HIT.")
                    # Construct a Directus-like response from cached data.
                    return {
                        "hashed_user_id": hashed_user_id,
                        "app_id": app_id,
                        "item_key": item_key,
                        "encrypted_item_json": cached_encrypted_json,
                        # Note: 'id', 'created_at', 'updated_at', etc. won't be in cache
                    }
            except Exception as e_cache_get:
                logger.error(f"{log_prefix} Error getting item from cache: {e_cache_get}", exc_info=True)
        else:
            logger.warning(f"{log_prefix} Cache service not available for get_user_app_item_raw.")

        # 2. If not in cache or cache error, fetch from Directus
        logger.info(f"{log_prefix} Cache MISS or cache service unavailable. Fetching from Directus.")
        params = {
            "filter": {
                "hashed_user_id": {"_eq": hashed_user_id},
                "app_id": {"_eq": app_id},
                "item_key": {"_eq": item_key}
            },
            "limit": 1,
            "fields": "id,hashed_user_id,app_id,item_key,item_type,encrypted_item_json,encrypted_app_key,created_at,updated_at,item_version,sequence_number"
        }
        
        try:
            items = await self._service.get_items(self.COLLECTION_NAME, params=params, no_cache=True)
            if items:
                directus_item = items[0]
                logger.info(f"{log_prefix} Fetched item from Directus: ID {directus_item.get('id')}")

                # 3. Store in cache if fetched from Directus
                if self._service.cache_service and directus_item.get("encrypted_item_json") is not None:
                    try:
                        await self._service.cache_service.set_user_app_settings_and_memories_item(
                            user_id_hash=hashed_user_id,
                            app_id=app_id,
                            item_key=item_key,
                            encrypted_value_json=directus_item["encrypted_item_json"]
                        )
                        logger.info(f"{log_prefix} Stored item (ID {directus_item.get('id')}) in cache.")
                    except Exception as e_cache_set:
                        logger.error(f"{log_prefix} Error storing item (ID {directus_item.get('id')}) in cache: {e_cache_set}", exc_info=True)
                return directus_item
            
            logger.info(f"{log_prefix} No item found in Directus.")
            return None
        except Exception as e_directus:
            logger.error(f"{log_prefix} Error fetching item from Directus: {e_directus}", exc_info=True)
            return None

    async def set_user_app_item_raw(
        self,
        user_id: str,
        app_id: str,
        item_key: str,
        encrypted_item_json: Optional[str],
        current_timestamp: int
    ) -> Optional[Dict[str, Any]]:
        """
        Creates or updates a raw user app setting or memory item with encrypted_item_json.
        Timestamps should be provided by the caller.

        Args:
            user_id: The user's ID (will be hashed for Directus storage)
            app_id: The app identifier
            item_key: The item key within the app
            encrypted_item_json: The encrypted JSON data
            current_timestamp: Unix timestamp for created_at/updated_at

        Returns:
            The created/updated Directus item dictionary or None on failure.
        """
        hashed_user_id = self._hash_user_id(user_id)
        existing_item = await self.get_user_app_item_raw(user_id, app_id, item_key)
        
        payload = {
            "hashed_user_id": hashed_user_id,
            "app_id": app_id,
            "item_key": item_key,
            "encrypted_item_json": encrypted_item_json,
            "updated_at": current_timestamp
        }

        log_prefix = f"AppSettingsAndMemoriesMethods.set_user_app_item_raw (User: {user_id[:8]}..., App: {app_id}, Key: {item_key}):"
        
        directus_result_item: Optional[Dict[str, Any]] = None
        try:
            if existing_item and existing_item.get("id"):
                item_id = existing_item["id"]
                logger.info(f"{log_prefix} Updating existing item in Directus, ID {item_id}.")
                directus_result_item = await self._service.update_item(self.COLLECTION_NAME, item_id, payload)
            else:
                payload["created_at"] = current_timestamp # Set created_at only for new items
                logger.info(f"{log_prefix} Creating new item in Directus.")
                directus_result_item = await self._service.create_item(self.COLLECTION_NAME, payload)

            # After successful Directus operation, update cache
            if directus_result_item and self._service.cache_service:
                if encrypted_item_json is not None:
                    logger.info(f"{log_prefix} Updating cache for item ID {directus_result_item.get('id')}.")
                    try:
                        await self._service.cache_service.set_user_app_settings_and_memories_item(
                            user_id_hash=hashed_user_id,
                            app_id=app_id,
                            item_key=item_key,
                            encrypted_value_json=encrypted_item_json
                        )
                    except Exception as e_cache_set:
                        logger.error(f"{log_prefix} Error updating cache after Directus set: {e_cache_set}", exc_info=True)
                else:
                    logger.info(f"{log_prefix} Value is None, deleting item from cache.")
                    try:
                        await self._service.cache_service.delete_user_app_settings_and_memories_item(
                            user_id_hash=hashed_user_id,
                            app_id=app_id,
                            item_key=item_key
                        )
                    except Exception as e_cache_del:
                         logger.error(f"{log_prefix} Error deleting item from cache after Directus set (value was None): {e_cache_del}", exc_info=True)
            elif not self._service.cache_service:
                logger.warning(f"{log_prefix} Cache service not available for set_user_app_item_raw.")
            
            return directus_result_item

        except Exception as e_directus:
            logger.error(f"{log_prefix} Error during Directus operation: {e_directus}", exc_info=True)
            return None

    async def delete_user_app_item_raw(self, user_id: str, app_id: str, item_key: str) -> bool:
        """
        Deletes a user app setting or memory item for a given user_id, app_id, and item_key.
        Returns True if deletion was successful or item didn't exist, False on error.
        """
        hashed_user_id = self._hash_user_id(user_id)
        existing_item = await self.get_user_app_item_raw(user_id, app_id, item_key)
        if not existing_item or not existing_item.get("id"):
            logger.debug(f"No app item found to delete for user {user_id[:8]}..., app {app_id}, key {item_key}. Considered successful.")
            return True

        log_prefix = f"AppSettingsAndMemoriesMethods.delete_user_app_item_raw (User: {user_id[:8]}..., App: {app_id}, Key: {item_key}):"
        item_id = existing_item["id"]
        logger.info(f"{log_prefix} Deleting item from Directus, ID {item_id}.")
        
        try:
            directus_delete_success = await self._service.delete_item(self.COLLECTION_NAME, item_id)
            
            if directus_delete_success:
                logger.info(f"{log_prefix} Successfully deleted item from Directus, ID {item_id}.")
                if self._service.cache_service:
                    logger.info(f"{log_prefix} Deleting item from cache.")
                    try:
                        await self._service.cache_service.delete_user_app_settings_and_memories_item(
                            user_id_hash=hashed_user_id,
                            app_id=app_id,
                            item_key=item_key
                        )
                    except Exception as e_cache_del:
                        logger.error(f"{log_prefix} Error deleting item from cache after Directus delete: {e_cache_del}", exc_info=True)
                elif not self._service.cache_service:
                    logger.warning(f"{log_prefix} Cache service not available for delete_user_app_item_raw.")
                return True
            else:
                logger.warning(f"{log_prefix} Failed to delete item from Directus, ID {item_id}.")
                return False
        except Exception as e_directus:
            logger.error(f"{log_prefix} Error during Directus delete operation for ID {item_id}: {e_directus}", exc_info=True)
            return False

    async def get_user_app_data_metadata(self, user_id: str, app_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches metadata (app_id, item_key, item_type) for all app settings/memories for a given user_id.
        Optionally filters by a specific app_id.
        """
        hashed_user_id = self._hash_user_id(user_id)
        filter_conditions = {"hashed_user_id": {"_eq": hashed_user_id}}
        if app_id:
            filter_conditions["app_id"] = {"_eq": app_id}
        
        params = {
            "filter": filter_conditions,
            "fields": "app_id,item_key,item_type"
        }
        log_message = f"Fetching app data metadata for user {user_id[:8]}..."
        if app_id:
            log_message += f", app_id: {app_id}"
        logger.debug(log_message + f" with params: {params}")
        
        try:
            items = await self._service.get_items(self.COLLECTION_NAME, params=params, no_cache=True)
            logger.debug(f"Fetched {len(items)} app data metadata items for user {user_id[:8]}...")
            return items
        except Exception as e:
            logger.error(f"Error in get_user_app_data_metadata for user {user_id[:8]}...: {str(e)}", exc_info=True)
            return []

    async def get_all_user_app_data_raw(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Fetches all raw app settings and memory items for a given user_id.
        Returns all fields needed for client sync.

        Used for sync after Phase 3 chat sync completes.

        Args:
            user_id: The user's ID (will be hashed for Directus query)

        Returns:
            A list of Directus item dictionaries with all sync-relevant fields.
        """
        hashed_user_id = self._hash_user_id(user_id)
        params = {
            "filter": {
                "hashed_user_id": {"_eq": hashed_user_id}
            },
            # Fetch all fields needed for client sync
            "fields": "id,app_id,item_key,item_type,encrypted_item_json,encrypted_app_key,created_at,updated_at,item_version,sequence_number"
        }
        logger.debug(f"Fetching all raw app items for user {user_id[:8]}...")
        try:
            items = await self._service.get_items(self.COLLECTION_NAME, params=params, no_cache=True)
            logger.debug(f"Fetched {len(items)} raw app items for user {user_id[:8]}...")
            return items
        except Exception as e:
            logger.error(f"Error in get_all_user_app_data_raw for user {user_id[:8]}...: {str(e)}", exc_info=True)
            return []
    async def get_decrypted_user_app_item_value(
        self,
        user_id: str,
        app_id: str,
        item_key: str,
        user_vault_key_id: str
    ) -> Optional[Any]: # Return type can be Any as JSON can be diverse
        """
        Fetches a specific app setting/memory item for a user and decrypts its JSON value.

        Note: This method is for server-side decryption using Vault keys, which is only used
        when the user has explicitly confirmed sharing data (e.g., during AI processing).
        Normal sync uses client-side decryption.

        Args:
            user_id: The user's ID (will be hashed for Directus query)
            app_id: The ID of the app.
            item_key: The key of the item.
            user_vault_key_id: The user's Vault key ID for decryption.

        Returns:
            The decrypted value (parsed from JSON) of the item, or None if not found or decryption/parsing fails.
        """
        raw_item = await self.get_user_app_item_raw(user_id, app_id, item_key)
        if not raw_item:
            logger.warning(f"No app item found for user {user_id[:8]}..., app {app_id}, key {item_key} during decryption attempt.")
            return None
            
        encrypted_json = raw_item.get("encrypted_item_json")

        if not encrypted_json:
            logger.warning(f"App item found for user {user_id[:8]}..., app {app_id}, key {item_key}, but encrypted_item_json is missing or empty.")
            return None

        if not user_vault_key_id:
            logger.error(f"Cannot decrypt item for user {user_id[:8]}..., app {app_id}, key {item_key}: user_vault_key_id is missing.")
            return None

        decrypted_json_string = await self._service.encryption_service.decrypt_with_user_key(
            ciphertext=encrypted_json,
            key_id=user_vault_key_id
        )

        if decrypted_json_string is None:
            logger.error(f"Failed to decrypt app item for user {user_id[:8]}..., app {app_id}, key {item_key}. Decryption returned None.")
            return None
        
        try:
            import json
            decrypted_value = json.loads(decrypted_json_string)
            logger.info(f"Successfully fetched, decrypted, and parsed app item for user {user_id[:8]}..., app {app_id}, key {item_key}")
            return decrypted_value
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decrypted JSON for app item user {user_id[:8]}..., app {app_id}, key {item_key}. Error: {str(e)}. Decrypted string: '{decrypted_json_string[:100]}...'")
            return None 
        except Exception as e:
            logger.error(f"Unexpected error parsing decrypted JSON for app item user {user_id[:8]}..., app {app_id}, key {item_key}: {str(e)}", exc_info=True)
            return None