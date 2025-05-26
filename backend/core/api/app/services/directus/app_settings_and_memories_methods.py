# File: backend/core/api/app/services/directus/app_settings_and_memories_methods.py
# Description: Methods for interacting with the 'user_app_settings_and_memories' collection in Directus.

import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .directus import DirectusService # Import for type hinting

logger = logging.getLogger(__name__)

class AppSettingsAndMemoriesMethods:
    """
    Contains methods for interacting with the 'user_app_settings_and_memories' collection in Directus.
    This class replaces the previous AppSettingMethods and AppMemoryMethods.
    """
    COLLECTION_NAME = "user_app_settings_and_memories"

    def __init__(self, service: 'DirectusService'):
        self._service = service # Store reference to the main DirectusService instance

    async def get_user_app_item_raw(self, user_id_hash: str, app_id: str, item_key: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a raw user app setting or memory item (including encrypted_item_value_json)
        for a given user_id_hash, app_id, and item_key.
        Tries cache first, then Directus. Updates cache if fetched from Directus.

        Returns:
            The Directus-like item dictionary if found, else None.
        """
        log_prefix = f"AppSettingsAndMemoriesMethods.get_user_app_item_raw (User: {user_id_hash}, App: {app_id}, Key: {item_key}):"

        # 1. Try to get from cache
        if self._service.cache_service:
            try:
                cached_encrypted_value_json = await self._service.cache_service.get_user_app_settings_and_memories_item(
                    user_id_hash=user_id_hash,
                    app_id=app_id,
                    item_key=item_key
                )
                if cached_encrypted_value_json is not None: # Can be empty string if that's the stored value
                    logger.info(f"{log_prefix} Cache HIT.")
                    # Construct a Directus-like response from cached data.
                    # Note: 'id', 'created_at', 'updated_at' won't be in cache, but 'encrypted_item_value_json' is key.
                    return {
                        "user_id_hash": user_id_hash,
                        "app_id": app_id,
                        "item_key": item_key,
                        "encrypted_item_value_json": cached_encrypted_value_json,
                        # 'id', 'created_at', 'updated_at' are not stored with the value in this cache item.
                        # If these are strictly needed by callers even for cached items, this strategy needs adjustment
                        # or callers must be aware. For decryption, only encrypted_item_value_json is vital.
                    }
            except Exception as e_cache_get:
                logger.error(f"{log_prefix} Error getting item from cache: {e_cache_get}", exc_info=True)
        else:
            logger.warning(f"{log_prefix} Cache service not available for get_user_app_item_raw.")

        # 2. If not in cache or cache error, fetch from Directus
        logger.info(f"{log_prefix} Cache MISS or cache service unavailable. Fetching from Directus.")
        params = {
            "filter": {
                "user_id_hash": {"_eq": user_id_hash},
                "app_id": {"_eq": app_id},
                "item_key": {"_eq": item_key}
            },
            "limit": 1,
            "fields": "id,user_id_hash,app_id,item_key,encrypted_item_value_json,created_at,updated_at" # Ensure all fields are fetched
        }
        
        try:
            items = await self._service.get_items(self.COLLECTION_NAME, params=params, no_cache=True) # no_cache for Directus call itself
            if items:
                directus_item = items[0]
                logger.info(f"{log_prefix} Fetched item from Directus: ID {directus_item.get('id')}")

                # 3. Store in cache if fetched from Directus
                if self._service.cache_service and directus_item.get("encrypted_item_value_json") is not None:
                    try:
                        await self._service.cache_service.set_user_app_settings_and_memories_item(
                            user_id_hash=user_id_hash,
                            app_id=app_id,
                            item_key=item_key,
                            encrypted_value_json=directus_item["encrypted_item_value_json"]
                            # TTL is handled by CacheUserMixin's USER_APP_DATA_TTL
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
        user_id_hash: str,
        app_id: str,
        item_key: str,
        encrypted_item_value_json: Optional[str],
        current_timestamp: int
    ) -> Optional[Dict[str, Any]]:
        """
        Creates or updates a raw user app setting or memory item with encrypted_item_value_json.
        Timestamps should be provided by the caller.

        Returns:
            The created/updated Directus item dictionary or None on failure.
        """
        existing_item = await self.get_user_app_item_raw(user_id_hash, app_id, item_key)
        
        payload = {
            "user_id_hash": user_id_hash,
            "app_id": app_id,
            "item_key": item_key,
            "encrypted_item_value_json": encrypted_item_value_json,
            "updated_at": current_timestamp
        }

        log_prefix = f"AppSettingsAndMemoriesMethods.set_user_app_item_raw (User: {user_id_hash}, App: {app_id}, Key: {item_key}):"
        
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
                if encrypted_item_value_json is not None: # Value exists or is an empty string
                    logger.info(f"{log_prefix} Updating cache for item ID {directus_result_item.get('id')}.")
                    try:
                        await self._service.cache_service.set_user_app_settings_and_memories_item(
                            user_id_hash=user_id_hash,
                            app_id=app_id,
                            item_key=item_key,
                            encrypted_value_json=encrypted_item_value_json
                        )
                    except Exception as e_cache_set:
                        logger.error(f"{log_prefix} Error updating cache after Directus set: {e_cache_set}", exc_info=True)
                else: # encrypted_item_value_json is None, so delete from cache
                    logger.info(f"{log_prefix} Value is None, deleting item from cache.")
                    try:
                        await self._service.cache_service.delete_user_app_settings_and_memories_item(
                            user_id_hash=user_id_hash,
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

    async def delete_user_app_item_raw(self, user_id_hash: str, app_id: str, item_key: str) -> bool:
        """
        Deletes a user app setting or memory item for a given user_id_hash, app_id, and item_key.
        Returns True if deletion was successful or item didn't exist, False on error.
        """
        existing_item = await self.get_user_app_item_raw(user_id_hash, app_id, item_key)
        if not existing_item or not existing_item.get("id"):
            logger.debug(f"No app item found to delete for user {user_id_hash}, app {app_id}, key {item_key}. Considered successful.")
            return True

        log_prefix = f"AppSettingsAndMemoriesMethods.delete_user_app_item_raw (User: {user_id_hash}, App: {app_id}, Key: {item_key}):"
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
                            user_id_hash=user_id_hash,
                            app_id=app_id,
                            item_key=item_key
                        )
                    except Exception as e_cache_del:
                        logger.error(f"{log_prefix} Error deleting item from cache after Directus delete: {e_cache_del}", exc_info=True)
                elif not self._service.cache_service:
                    logger.warning(f"{log_prefix} Cache service not available for delete_user_app_item_raw.")
                return True # Return True if Directus delete was successful
            else:
                logger.warning(f"{log_prefix} Failed to delete item from Directus, ID {item_id}.")
                return False
        except Exception as e_directus:
            logger.error(f"{log_prefix} Error during Directus delete operation for ID {item_id}: {e_directus}", exc_info=True)
            return False

    async def get_user_app_data_metadata(self, user_id_hash: str, app_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches metadata (app_id, item_key) for all app settings/memories for a given user_id_hash.
        Optionally filters by a specific app_id.
        """
        filter_conditions = {"user_id_hash": {"_eq": user_id_hash}}
        if app_id:
            filter_conditions["app_id"] = {"_eq": app_id}
        
        params = {
            "filter": filter_conditions,
            "fields": "app_id,item_key" # Comma-separated string for fields
        }
        log_message = f"Fetching app data metadata for user_id_hash: {user_id_hash}"
        if app_id:
            log_message += f", app_id: {app_id}"
        logger.debug(log_message + f" with params: {params}")
        
        try:
            items = await self._service.get_items(self.COLLECTION_NAME, params=params, no_cache=True)
            logger.debug(f"Fetched {len(items)} app data metadata items for user_id_hash: {user_id_hash}")
            return items
        except Exception as e:
            logger.error(f"Error in get_user_app_data_metadata for user_id_hash {user_id_hash}: {str(e)}", exc_info=True)
            return []

    async def get_all_user_app_data_raw(self, user_id_hash: str) -> List[Dict[str, Any]]:
        """
        Fetches all raw app settings and memory items (app_id, item_key, encrypted_item_value_json)
        for a given user_id_hash.

        Used for cache warming.

        Returns:
            A list of Directus item dictionaries.
        """
        params = {
            "filter": {
                "user_id_hash": {"_eq": user_id_hash}
            },
            "fields": "app_id,item_key,encrypted_item_value_json" # Comma-separated string for fields
            # No limit, fetch all for the user
        }
        logger.debug(f"Fetching all raw app items for user_id_hash: {user_id_hash}")
        try:
            items = await self._service.get_items(self.COLLECTION_NAME, params=params, no_cache=True)
            logger.debug(f"Fetched {len(items)} raw app items for user_id_hash: {user_id_hash}")
            return items
        except Exception as e:
            logger.error(f"Error in get_all_user_app_data_raw for user_id_hash {user_id_hash}: {str(e)}", exc_info=True)
            return []
    async def get_decrypted_user_app_item_value(
        self,
        user_id_hash: str,
        app_id: str,
        item_key: str,
        user_vault_key_id: str
    ) -> Optional[Any]: # Return type can be Any as JSON can be diverse
        """
        Fetches a specific app setting/memory item for a user and decrypts its JSON value.

        Args:
            user_id_hash: The hashed ID of the user.
            app_id: The ID of the app.
            item_key: The key of the item.
            user_vault_key_id: The user's Vault key ID for decryption.

        Returns:
            The decrypted value (parsed from JSON) of the item, or None if not found or decryption/parsing fails.
        """
        raw_item = await self.get_user_app_item_raw(user_id_hash, app_id, item_key)
        if not raw_item:
            logger.warning(f"No app item found for user {user_id_hash}, app {app_id}, key {item_key} during decryption attempt.")
            return None
            
        encrypted_value_json = raw_item.get("encrypted_item_value_json")

        if not encrypted_value_json:
            logger.warning(f"App item found for user {user_id_hash}, app {app_id}, key {item_key}, but encrypted_item_value_json is missing or empty.")
            return None # Or an empty dict/list depending on expected value if not found

        if not user_vault_key_id:
            logger.error(f"Cannot decrypt item for user {user_id_hash}, app {app_id}, key {item_key}: user_vault_key_id is missing.")
            return None

        decrypted_json_string = await self._service.encryption_service.decrypt_with_user_key(
            ciphertext=encrypted_value_json,
            key_id=user_vault_key_id
        )

        if decrypted_json_string is None:
            logger.error(f"Failed to decrypt app item for user {user_id_hash}, app {app_id}, key {item_key}. Decryption returned None.")
            return None
        
        try:
            # Assuming the decrypted string is valid JSON
            import json
            decrypted_value = json.loads(decrypted_json_string)
            logger.info(f"Successfully fetched, decrypted, and parsed app item for user {user_id_hash}, app {app_id}, key {item_key}")
            return decrypted_value
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decrypted JSON for app item user {user_id_hash}, app {app_id}, key {item_key}. Error: {str(e)}. Decrypted string: '{decrypted_json_string[:100]}...'")
            # Fallback: return the raw decrypted string if it's not JSON, or handle as error
            # For now, returning None as the expectation is a JSON parsable value.
            # If non-JSON strings are valid, this logic needs adjustment.
            return None 
        except Exception as e: # Catch any other unexpected errors during parsing
            logger.error(f"Unexpected error parsing decrypted JSON for app item user {user_id_hash}, app {app_id}, key {item_key}: {str(e)}", exc_info=True)
            return None