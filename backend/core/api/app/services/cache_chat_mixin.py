import logging
from typing import Any, Optional, Union, List, Tuple, Literal, Dict
from datetime import datetime, timezone
from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData, MessageInCache

logger = logging.getLogger(__name__)

class ChatCacheMixin:
    """Mixin for new chat sync architecture caching methods"""

    def get_chat_key(self, chat_id: str) -> str:
        """
        Returns a generic cache key for a chat, primarily identified by its chat_id.
        This key can be used for tasks or general references to a chat entity.
        """
        return f"chat:{chat_id}"
    
    # New Chat Suggestions Caching
    def _get_new_chat_suggestions_key(self, hashed_user_id: str) -> str:
        """Returns the cache key for new chat suggestions for a user."""
        return f"user:{hashed_user_id}:new_chat_suggestions"
    
    async def set_new_chat_suggestions(self, hashed_user_id: str, suggestions: List[Dict[str, Any]], ttl: int = 600) -> bool:
        """
        Cache new chat suggestions for a user.
        
        Args:
            hashed_user_id: SHA256 hash of user_id
            suggestions: List of suggestion dictionaries
            ttl: Time to live in seconds (default: 10 minutes)
        
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.error("Redis client not available for set_new_chat_suggestions")
            return False
        
        key = self._get_new_chat_suggestions_key(hashed_user_id)
        try:
            import json
            # Store as JSON string
            suggestions_json = json.dumps(suggestions)
            await client.set(key, suggestions_json, ex=ttl)
            logger.debug(f"Cached {len(suggestions)} new chat suggestions for user {hashed_user_id[:8]}... with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching new chat suggestions for user {hashed_user_id[:8]}...: {e}", exc_info=True)
            return False
    
    async def get_new_chat_suggestions(self, hashed_user_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached new chat suggestions for a user.
        
        Args:
            hashed_user_id: SHA256 hash of user_id
        
        Returns:
            List of suggestion dictionaries if cached, None otherwise
        """
        client = await self.client
        if not client:
            logger.error("Redis client not available for get_new_chat_suggestions")
            return None
        
        key = self._get_new_chat_suggestions_key(hashed_user_id)
        try:
            suggestions_json = await client.get(key)
            if suggestions_json:
                import json
                suggestions = json.loads(suggestions_json)
                logger.debug(f"Cache HIT: Retrieved {len(suggestions)} new chat suggestions for user {hashed_user_id[:8]}...")
                return suggestions
            else:
                logger.debug(f"Cache MISS: No new chat suggestions cached for user {hashed_user_id[:8]}...")
                return None
        except Exception as e:
            logger.error(f"Error retrieving new chat suggestions for user {hashed_user_id[:8]}...: {e}", exc_info=True)
            return None
    
    async def delete_new_chat_suggestions(self, hashed_user_id: str) -> bool:
        """
        Delete (invalidate) cached new chat suggestions for a user.
        This is called when a suggestion is deleted on the server,
        forcing a fresh fetch from Directus on next sync.
        
        Args:
            hashed_user_id: SHA256 hash of user_id
        
        Returns:
            True if deletion was successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.error("Redis client not available for delete_new_chat_suggestions")
            return False
        
        key = self._get_new_chat_suggestions_key(hashed_user_id)
        try:
            deleted_count = await client.delete(key)
            if deleted_count > 0:
                logger.debug(f"Cache INVALIDATED: Deleted new chat suggestions cache for user {hashed_user_id[:8]}...")
                return True
            else:
                logger.debug(f"Cache key not found for new chat suggestions (user {hashed_user_id[:8]}...)")
                return True  # Not an error if key doesn't exist
        except Exception as e:
            logger.error(f"Error deleting new chat suggestions cache for user {hashed_user_id[:8]}...: {e}", exc_info=True)
            return False
    
    # 1. user:{user_id}:chat_ids_versions (Sorted Set: score=last_edited_overall_timestamp, value=chat_id)
    def _get_user_chat_ids_versions_key(self, user_id: str) -> str:
        return f"user:{user_id}:chat_ids_versions"

    async def add_chat_to_ids_versions(self, user_id: str, chat_id: str, last_edited_overall_timestamp: int) -> bool:
        """Adds a chat_id to the sorted set, scored by its last_edited_overall_timestamp."""
        client = await self.client
        if not client:
            logger.error("[REDIS_DEBUG] No Redis client available for add_chat_to_ids_versions")
            return False
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            logger.debug(f"[REDIS_DEBUG] ZADD for key '{key}', chat_id '{chat_id}', score '{float(last_edited_overall_timestamp)}'")
            result = await client.zadd(key, {chat_id: float(last_edited_overall_timestamp)})
            logger.debug(f"[REDIS_DEBUG] ZADD result: {result} (1=new, 0=updated)")
            
            # Verify the add worked
            count = await client.zcard(key)
            logger.debug(f"[REDIS_DEBUG] Current count in sorted set '{key}': {count}")
            
            ttl_to_set = self.CHAT_IDS_VERSIONS_TTL
            logger.debug(f"[REDIS_DEBUG] Setting EXPIRE for key '{key}' with TTL {ttl_to_set}s")
            await client.expire(key, ttl_to_set)
            
            # Verify TTL was set
            ttl_check = await client.ttl(key)
            logger.debug(f"[REDIS_DEBUG] Verified TTL for key '{key}': {ttl_check}s")
            
            logger.debug(f"[REDIS_DEBUG] Successfully added chat '{chat_id}' to sorted set '{key}' (total: {count})")
            return True
        except Exception as e:
            logger.error(f"[REDIS_DEBUG] Error adding chat {chat_id} to {key}: {e}", exc_info=True)
            return False

    async def remove_chat_from_ids_versions(self, user_id: str, chat_id: str) -> bool:
        """Removes a chat_id from the sorted set."""
        client = await self.client
        if not client:
            return False
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            removed_count = await client.zrem(key, chat_id)
            return removed_count > 0
        except Exception as e:
            logger.error(f"Error removing chat {chat_id} from {key}: {e}")
            return False

    async def get_chat_ids_versions(
        self, user_id: str, start: int = 0, end: int = -1, with_scores: bool = False, reverse: bool = True
    ) -> Union[List[str], List[Tuple[str, float]]]:
        """Gets chat_ids from the sorted set, optionally with scores. Sorted by score descending (most recent first) by default."""
        client = await self.client
        if not client:
            logger.error("[REDIS_DEBUG] No Redis client available for get_chat_ids_versions")
            return []
        key = self._get_user_chat_ids_versions_key(user_id)
        logger.debug(f"[REDIS_DEBUG] Getting chat IDs from key: {key}, range: {start}-{end}, reverse: {reverse}")
        try:
            # Check if key exists and get count
            exists = await client.exists(key)
            if exists:
                count = await client.zcard(key)
                logger.debug(f"[REDIS_DEBUG] Key '{key}' exists with {count} items")
            else:
                # This is expected when cache hasn't been warmed yet or user has no chats
                # Use debug level instead of warning to avoid noise in logs
                logger.debug(f"[REDIS_DEBUG] Key '{key}' does not exist in Redis (this is normal if cache hasn't been warmed or user has no chats)")
                return []
            
            if reverse:
                items = await client.zrange(key, start, end, desc=True, withscores=with_scores)
            else:
                items = await client.zrange(key, start, end, desc=False, withscores=with_scores)
            
            logger.debug(f"[REDIS_DEBUG] Retrieved {len(items)} items from Redis for key '{key}'")
            
            if with_scores:
                result = [(item.decode('utf-8'), score) for item, score in items]
                logger.debug(f"[REDIS_DEBUG] Decoded items with scores: {result[:3] if len(result) > 3 else result}")
                return result
            else:
                result = [item.decode('utf-8') for item in items]
                logger.debug(f"[REDIS_DEBUG] Decoded items: {result[:3] if len(result) > 3 else result}")
                return result
        except Exception as e:
            logger.error(f"[REDIS_DEBUG] Error getting chat_ids_versions from {key}: {e}", exc_info=True)
            return []

    async def update_chat_score_in_ids_versions(self, user_id: str, chat_id: str, new_last_edited_overall_timestamp: int) -> bool:
        """Updates the score (timestamp) for a chat_id in the sorted set. Effectively an alias for add."""
        return await self.add_chat_to_ids_versions(user_id, chat_id, new_last_edited_overall_timestamp)

    async def get_chat_last_edited_overall_timestamp(self, user_id: str, chat_id: str) -> Optional[int]:
        """Gets the last_edited_overall_timestamp (score) for a specific chat_id from the user's sorted set."""
        client = await self.client
        if not client:
            logger.error(f"CACHE_OP_ERROR: Redis client not available for get_chat_last_edited_overall_timestamp for user {user_id}, chat {chat_id}.")
            return None
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            score = await client.zscore(key, chat_id)
            if score is not None:
                logger.debug(f"CACHE_OP_HIT: Successfully retrieved score for chat '{chat_id}' in sorted set '{key}': {score}")
                return int(score)
            else:
                logger.warning(f"CACHE_OP_MISS: Score not found for chat '{chat_id}' in sorted set '{key}'.")
                return None
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error getting score for chat {chat_id} from {key}: {e}", exc_info=True)
            return None

    async def check_chat_exists_for_user(self, user_id: str, chat_id: str) -> bool:
        """
        Efficiently checks if a chat_id exists in the user's chat list in cache.
        Returns True if the chat is present in the sorted set.
        """
        client = await self.client
        if not client:
            return False
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            score = await client.zscore(key, chat_id)
            return score is not None
        except Exception as e:
            logger.error(f"Error checking chat presence in cache for user {user_id}, chat {chat_id}: {e}")
            return False

    # 2. user:{user_id}:chat:{chat_id}:versions (Hash: messages_v, draft_v, title_v)
    def _get_chat_versions_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:versions"

    async def set_chat_versions(self, user_id: str, chat_id: str, versions: CachedChatVersions, ttl: Optional[int] = None) -> bool:
        """Sets the component versions for a chat."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_versions_key(user_id, chat_id)
        data_to_set = versions.model_dump()
        final_ttl = ttl if ttl is not None else self.CHAT_VERSIONS_TTL
        try:
            logger.debug(f"CACHE_OP: HMSET for key '{key}' with data: {data_to_set}")
            await client.hmset(key, data_to_set)
            logger.debug(f"CACHE_OP: EXPIRE for key '{key}' with TTL {final_ttl}s")
            await client.expire(key, final_ttl)
            logger.debug(f"CACHE_OP: Successfully set versions for key '{key}' with TTL {final_ttl}s. Data: {data_to_set}")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error setting versions for {key}. Data: {data_to_set}, TTL: {final_ttl}. Error: {e}", exc_info=True)
            return False

    async def get_chat_versions(self, user_id: str, chat_id: str) -> Optional[CachedChatVersions]:
        """Gets the component versions for a chat."""
        client = await self.client
        if not client:
            return None
        key = self._get_chat_versions_key(user_id, chat_id)
        logger.debug(f"CACHE_OP: HGETALL for key '{key}'")
        try:
            versions_data_bytes = await client.hgetall(key)
            if not versions_data_bytes:
                logger.warning(f"CACHE_OP_MISS: No versions data found for key '{key}'")
                return None
            versions_data = {k.decode('utf-8'): int(v.decode('utf-8')) for k, v in versions_data_bytes.items()}
            logger.debug(f"CACHE_OP_HIT: Successfully retrieved versions for key '{key}'. Data: {versions_data}")
            # Attempt to refresh TTL on successful get, if desired (can be added here or as a separate method)
            # await client.expire(key, self.CHAT_VERSIONS_TTL)
            return CachedChatVersions(**versions_data)
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error getting versions from {key}: {e}", exc_info=True)
            return None

    async def delete_chat_versions(self, user_id: str, chat_id: str) -> bool:
        """
        Deletes the chat versions hash for a specific user and chat.
        This removes the entire versions hash (messages_v, title_v, draft_v, etc.).
        Returns True if the key was deleted or did not exist, False on error.
        """
        client = await self.client
        if not client:
            logger.error("CACHE_OP_ERROR: Redis client not available for delete_chat_versions.")
            return False

        key = self._get_chat_versions_key(user_id, chat_id)
        try:
            logger.debug(f"CACHE_OP: DELETE for key '{key}' (chat versions)")
            deleted_count = await client.delete(key)
            if deleted_count > 0:
                logger.debug(f"CACHE_OP: Successfully deleted chat versions key '{key}'")
            else:
                logger.debug(f"CACHE_OP: Chat versions key '{key}' not found or already deleted")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error deleting chat versions key '{key}': {e}", exc_info=True)
            return False

    async def increment_chat_component_version(self, user_id: str, chat_id: str, component: str, increment_by: int = 1) -> Optional[int]:
        """
        Increments a specific component version for a chat in the versions hash.
        Returns the new version or None on error.
        The 'component' can be "messages_v", "title_v", or dynamic like f"user_draft_v:{specific_user_id}".
        """
        client = await self.client
        if not client:
            return None
        key = self._get_chat_versions_key(user_id, chat_id)
        final_ttl = self.CHAT_VERSIONS_TTL
        try:
            logger.debug(f"CACHE_OP: HINCRBY for key '{key}', component '{component}', increment_by '{increment_by}'")
            new_version = await client.hincrby(key, component, increment_by)
            
            # Ensure base fields (messages_v, title_v) exist in the hash, initializing to 0 if not.
            # This is crucial for CachedChatVersions model validation, especially if HINCRBY created the hash.
            # HSETNX will not overwrite existing values.
            await client.hsetnx(key, "messages_v", 0)
            await client.hsetnx(key, "title_v", 0)
            
            logger.debug(f"CACHE_OP: HINCRBY for key '{key}', component '{component}' returned new version '{new_version}'. Ensured base fields. EXPIRE with TTL {final_ttl}s.")
            await client.expire(key, final_ttl) # Ensure TTL is refreshed
            logger.debug(f"CACHE_OP: Successfully incremented component '{component}' for key '{key}' to '{new_version}'. Base fields ensured. TTL set to {final_ttl}s.")
            return new_version
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error incrementing component '{component}' for key '{key}'. Error: {e}", exc_info=True)
            return None

    async def set_chat_version_component(self, user_id: str, chat_id: str, component: str, value: int) -> bool:
        """
        Sets a specific component's version for a chat in the versions hash to an absolute value.
        Returns True on success, False on error.
        The 'component' can be "messages_v", "title_v", or dynamic like f"user_draft_v:{specific_user_id}".
        """
        client = await self.client
        if not client:
            return False
        key = self._get_chat_versions_key(user_id, chat_id)
        final_ttl = self.CHAT_VERSIONS_TTL
        try:
            logger.debug(f"CACHE_OP: HSET for key '{key}', component '{component}', value '{value}'")
            await client.hset(key, component, value)
            # Ensure base messages_v and title_v fields exist if the key itself is new or was missing fields.
            # This is important if hset is creating the hash for the first time with this component.
            await client.hsetnx(key, "messages_v", 0)
            await client.hsetnx(key, "title_v", 0)
            await client.expire(key, final_ttl) # Ensure TTL is set/refreshed
            logger.debug(f"CACHE_OP: Successfully set component '{component}' for key '{key}' to '{value}'. TTL set to {final_ttl}s.")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error setting component '{component}' for key '{key}' to '{value}'. Error: {e}", exc_info=True)
            return False

    # --- User-Specific Draft Cache Methods ---

    def _get_user_chat_draft_key(self, user_id: str, chat_id: str) -> str:
        """Returns the cache key for a user's specific draft in a chat."""
        return f"user:{user_id}:chat:{chat_id}:draft"

    async def increment_user_draft_version(self, user_id: str, chat_id: str, increment_by: int = 1) -> Optional[int]:
        """
        Increments the draft version for a specific user in a specific chat.
        This updates version in two places:
        1. `draft_v` in `user:{user_id}:chat:{chat_id}:draft` (the dedicated draft key)
        2. `user_draft_v:{user_id}` in `user:{user_id}:chat:{chat_id}:versions` (the general versions key for the chat)
        Attempts to be resilient to cache expiration of the dedicated draft key by checking the general versions key.
        Returns the new draft version or None on error.
        """
        client = await self.client
        if not client:
            return None

        draft_key = self._get_user_chat_draft_key(user_id, chat_id)
        versions_key = self._get_chat_versions_key(user_id, chat_id)
        user_specific_draft_version_field = f"user_draft_v:{user_id}"
        
        new_draft_version_for_dedicated_key: Optional[int] = None
        try:
            # Check if the dedicated draft key's draft_v field exists
            dedicated_draft_v_exists = await client.hexists(draft_key, "draft_v")

            current_version_base = 0 # Default base if no version info found
            if not dedicated_draft_v_exists:
                # Dedicated draft_v doesn't exist. Try to get a base from the general versions key.
                logger.debug(f"Dedicated draft_v missing for {draft_key}. Checking general versions key {versions_key} field {user_specific_draft_version_field}.")
                general_versions_data_bytes = await client.hget(versions_key, user_specific_draft_version_field)
                if general_versions_data_bytes:
                    try:
                        current_version_base = int(general_versions_data_bytes.decode('utf-8'))
                        logger.debug(f"Found base version {current_version_base} from general versions key for {draft_key}.")
                        # Explicitly set this base in the dedicated draft key.
                        # Hincrby will then increment this value.
                        await client.hset(draft_key, "draft_v", current_version_base)
                    except ValueError:
                        logger.warning(f"Could not parse version from general key for {draft_key}. Defaulting base to 0 for hincrby.")
                        # current_version_base remains 0, hincrby will effectively start from increment_by
                else:
                    logger.debug(f"No base version found in general versions key for {draft_key}. Hincrby will start from 0 + increment_by.")
                    # current_version_base remains 0, hincrby will effectively start from increment_by
            
            # Increment in the dedicated draft key.
            # If "draft_v" was just set from general key, hincrby increments it.
            # If "draft_v" existed, hincrby increments it.
            # If "draft_v" did not exist and no base found, hincrby creates it starting from 0 + increment_by.
            new_draft_version_for_dedicated_key = await client.hincrby(draft_key, "draft_v", increment_by)
            await client.expire(draft_key, self.USER_DRAFT_TTL)

            # Now, ensure the general versions key is also updated consistently to match the new authoritative version.
            await client.hset(versions_key, user_specific_draft_version_field, new_draft_version_for_dedicated_key)
            
            # Ensure base messages_v and title_v fields exist in the general versions key if the key itself is new or was missing fields.
            await client.hsetnx(versions_key, "messages_v", 0)
            await client.hsetnx(versions_key, "title_v", 0)
            await client.expire(versions_key, self.CHAT_VERSIONS_TTL) # Refresh TTL for the general versions key
            
            logger.debug(f"Incremented draft version for user {user_id}, chat {chat_id} to {new_draft_version_for_dedicated_key}. Synced with general versions key.")
            return new_draft_version_for_dedicated_key
        except Exception as e:
            logger.error(f"Error incrementing draft version for user {user_id}, chat {chat_id}: {e}", exc_info=True)
            return None

    async def update_user_draft_in_cache(self, user_id: str, chat_id: str, encrypted_draft_md: Optional[str], draft_version: int) -> bool:
        """
        Updates the user's draft content and version in their dedicated draft cache key.
        Sets TTL for the draft key.
        """
        client = await self.client
        if not client:
            return False
        key = self._get_user_chat_draft_key(user_id, chat_id)
        try:
            payload = {"draft_v": draft_version}
            if encrypted_draft_md is None:
                payload["encrypted_draft_md"] = "null" # Store null as a string "null"
            else:
                payload["encrypted_draft_md"] = encrypted_draft_md
            
            await client.hmset(key, payload)
            await client.expire(key, self.USER_DRAFT_TTL) # Assuming USER_DRAFT_TTL is defined
            logger.debug(f"Updated draft for user {user_id}, chat {chat_id} with version {draft_version}")
            return True
        except Exception as e:
            logger.error(f"Error updating draft for user {user_id}, chat {chat_id}: {e}")
            return False

    async def get_user_draft_from_cache(self, user_id: str, chat_id: str, refresh_ttl: bool = False) -> Optional[Tuple[Optional[str], int]]:
        """
        Gets the user's draft content (encrypted markdown string) and version from cache.
        Returns a tuple (encrypted_draft_md, draft_version) or None if not found or error.
        "null" string for encrypted_draft_md is converted back to None.
        """
        client = await self.client
        if not client:
            return None
        key = self._get_user_chat_draft_key(user_id, chat_id)
        try:
            draft_data_bytes = await client.hgetall(key)
            if not draft_data_bytes:
                return None
            
            draft_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in draft_data_bytes.items()}
            
            encrypted_md = draft_data.get("encrypted_draft_md")
            if encrypted_md == "null":
                encrypted_md = None
                
            version_str = draft_data.get("draft_v")
            if version_str is None: # Should not happen if set correctly
                logger.warning(f"Draft version missing for user {user_id}, chat {chat_id} in {key}")
                return None
            
            version = int(version_str)

            if refresh_ttl:
                await client.expire(key, self.USER_DRAFT_TTL)
            return encrypted_md, version
        except Exception as e:
            logger.error(f"Error getting draft for user {user_id}, chat {chat_id} from {key}: {e}")
            return None

    async def delete_user_draft_from_cache(self, user_id: str, chat_id: str) -> bool:
        """
        Deletes the user's specific draft cache key.
        Returns True if the key was deleted, False otherwise or on error.
        """
        client = await self.client
        if not client:
            return False
        key = self._get_user_chat_draft_key(user_id, chat_id)
        try:
            deleted_count = await client.delete(key)
            if deleted_count > 0:
                logger.debug(f"Successfully deleted draft cache key {key} for user {user_id}, chat {chat_id}.")
                return True
            else:
                logger.debug(f"Draft cache key {key} for user {user_id}, chat {chat_id} not found or already deleted.")
                return False # Or True, depending on if "not found" is a success for deletion
        except Exception as e:
            logger.error(f"Error deleting draft cache key {key} for user {user_id}, chat {chat_id}: {e}", exc_info=True)
            return False

    async def delete_user_draft_version_from_chat_versions(self, user_id: str, chat_id: str) -> bool:
        """
        Deletes the user-specific draft version field (e.g., user_draft_v:USER_ID)
        from the chat's general versions hash (user:{user_id}:chat:{chat_id}:versions).
        This is typically called when a draft is fully deleted to ensure its version
        counter doesn't persist and new drafts start from version 1.
        Returns True if the field was deleted or did not exist, False on Redis error.
        """
        client = await self.client
        if not client:
            logger.error("CACHE_OP_ERROR: Redis client not available for delete_user_draft_version_from_chat_versions.")
            return False

        versions_key = self._get_chat_versions_key(user_id, chat_id)
        user_specific_draft_version_field = f"user_draft_v:{user_id}"

        try:
            logger.debug(f"CACHE_OP: HDEL for key '{versions_key}', field '{user_specific_draft_version_field}'")
            # HDEL returns the number of fields that were removed.
            # If the field did not exist, it returns 0. This is a "successful" outcome for our purpose.
            # If the key does not exist, it is treated as an empty hash and HDEL returns 0.
            deleted_count = await client.hdel(versions_key, user_specific_draft_version_field)
            logger.debug(f"CACHE_OP: Processed HDEL for field '{user_specific_draft_version_field}' in key '{versions_key}'. Fields removed: {deleted_count}.")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error deleting field '{user_specific_draft_version_field}' from key '{versions_key}'. Error: {e}", exc_info=True)
            return False
            
    # 3. user:{user_id}:chat:{chat_id}:list_item_data (Hash: title (enc), unread_count)
    # Note: draft_json removed from this key as per new architecture
    def _get_chat_list_item_data_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:list_item_data"

    async def set_chat_list_item_data(self, user_id: str, chat_id: str, data: CachedChatListItemData, ttl: Optional[int] = None) -> bool:
        """Sets the list item data for a chat."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            # Ensure draft_json is not part of the model_dump if CachedChatListItemData still has it
            # Or better, update CachedChatListItemData schema to remove draft_json
            data_to_set = data.model_dump(exclude_none=True)
            if 'draft_json' in data_to_set: # Defensively remove if schema not yet updated
                del data_to_set['draft_json']
            
            # Redis hash values must be strings, bytes, ints, or floats.
            # Convert boolean values to int (0/1) for Redis compatibility.
            for k, v in data_to_set.items():
                if isinstance(v, bool):
                    data_to_set[k] = int(v)
            
            await client.hmset(key, data_to_set)
            await client.expire(key, ttl if ttl is not None else self.CHAT_LIST_ITEM_DATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error setting list_item_data for {key}: {e}")
            return False

    async def get_chat_list_item_data(self, user_id: str, chat_id: str, refresh_ttl: bool = False) -> Optional[CachedChatListItemData]:
        """Gets the list item data for a chat. Optionally refreshes TTL on access."""
        client = await self.client
        if not client:
            return None
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            data_bytes = await client.hgetall(key)
            if not data_bytes:
                return None
            
            data = {k.decode('utf-8'): v.decode('utf-8') for k, v in data_bytes.items()}
            if 'unread_count' in data:
                data['unread_count'] = int(data['unread_count'])
            # draft_json is no longer part of this key
            # Ensure the Pydantic model CachedChatListItemData is updated to not expect draft_json

            # Create a dictionary only with fields expected by the updated CachedChatListItemData
            filtered_data = {k: v for k, v in data.items() if k in CachedChatListItemData.model_fields}

            parsed_data = CachedChatListItemData(**filtered_data)
            if refresh_ttl:
                await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return parsed_data
        except Exception as e:
            logger.error(f"Error getting list_item_data from {key}: {e}")
            return None

    async def update_chat_list_item_field(self, user_id: str, chat_id: str, field: Literal["title", "unread_count", "last_mate_category"], value: Any) -> bool:
        """
        Updates a specific field in the chat's list_item_data. Refreshes TTL.
        'draft_json' is no longer managed here.
        """
        client = await self.client
        if not client:
            return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        
        if field == "draft_json": # Should not be called for draft_json anymore
            logger.warning(f"Attempted to update 'draft_json' via update_chat_list_item_field for {key}. This field is now managed separately.")
            return False
            
        try:
            await client.hset(key, field, value)
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error updating field {field} for {key}: {e}")
            return False

    async def increment_chat_list_item_unread_count(self, user_id: str, chat_id: str, increment_by: int = 1) -> Optional[int]:
        """Increments the unread_count for a chat. Refreshes TTL. Returns new count or None."""
        client = await self.client
        if not client:
            return None
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            new_count = await client.hincrby(key, "unread_count", increment_by)
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return new_count
        except Exception as e:
            logger.error(f"Error incrementing unread_count for {key}: {e}")
            return None
            
    async def refresh_chat_list_item_data_ttl(self, user_id: str, chat_id: str) -> bool:
        """Refreshes the TTL for the chat's list_item_data key."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            return await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
        except Exception as e:
            logger.error(f"Error refreshing TTL for {key}: {e}")
            return False

    async def update_chat_active_focus_id(self, user_id: str, chat_id: str, encrypted_focus_id: Optional[str]) -> bool:
        """
        Updates the encrypted_active_focus_id field in the chat's list_item_data.
        
        Args:
            user_id: The user ID
            chat_id: The chat ID
            encrypted_focus_id: The encrypted focus mode ID, or None to clear it
            
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            if encrypted_focus_id is None:
                # Remove the field if clearing focus mode
                await client.hdel(key, "encrypted_active_focus_id")
                logger.debug(f"CACHE_OP: Cleared encrypted_active_focus_id for chat {chat_id}")
            else:
                await client.hset(key, "encrypted_active_focus_id", encrypted_focus_id)
                logger.debug(f"CACHE_OP: Set encrypted_active_focus_id for chat {chat_id}")
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error updating encrypted_active_focus_id for {key}: {e}", exc_info=True)
            return False

    async def delete_chat_list_item_data(self, user_id: str, chat_id: str) -> bool:
        """
        Deletes the chat list item data hash for a specific user and chat.
        This removes the entire list_item_data hash (title, unread_count, last_mate_category, etc.).
        Returns True if the key was deleted or did not exist, False on error.
        """
        client = await self.client
        if not client:
            logger.error("CACHE_OP_ERROR: Redis client not available for delete_chat_list_item_data.")
            return False

        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            logger.debug(f"CACHE_OP: DELETE for key '{key}' (chat list item data)")
            deleted_count = await client.delete(key)
            if deleted_count > 0:
                logger.debug(f"CACHE_OP: Successfully deleted chat list item data key '{key}'")
            else:
                logger.debug(f"CACHE_OP: Chat list item data key '{key}' not found or already deleted")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error deleting chat list item data key '{key}': {e}", exc_info=True)
            return False

    # Scroll position and read status methods
    async def update_chat_scroll_position(self, user_id: str, chat_id: str, message_id: str) -> bool:
        """Updates the scroll position for a chat by storing the last visible message ID."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            await client.hset(key, "last_visible_message_id", message_id)
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            logger.debug(f"Updated scroll position for chat {chat_id}: message {message_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating scroll position for {key}: {e}")
            return False

    async def update_chat_read_status(self, user_id: str, chat_id: str, unread_count: int) -> bool:
        """Updates the read status (unread count) for a chat."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            await client.hset(key, "unread_count", unread_count)
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            logger.debug(f"Updated read status for chat {chat_id}: unread_count = {unread_count}")
            return True
        except Exception as e:
            logger.error(f"Error updating read status for {key}: {e}")
            return False

    # 4. user:{user_id}:chat:{chat_id}:messages:ai (List of VAULT-encrypted JSON Message strings for AI inference)
    # 5. user:{user_id}:chat:{chat_id}:messages:sync (List of CLIENT-encrypted JSON Message strings for client sync)
    
    def _get_ai_messages_key(self, user_id: str, chat_id: str) -> str:
        """Returns cache key for AI inference messages (vault-encrypted, last 3 chats, 72h TTL)"""
        return f"user:{user_id}:chat:{chat_id}:messages:ai"

    def _get_ai_cache_lru_key(self, user_id: str) -> str:
        """Returns cache key for tracking which chats have AI cache (sorted set by last activity)"""
        return f"user:{user_id}:ai_cache_lru"
    
    def _get_sync_messages_key(self, user_id: str, chat_id: str) -> str:
        """Returns cache key for client sync messages (client-encrypted, last 100 chats, 1h TTL)"""
        return f"user:{user_id}:chat:{chat_id}:messages:sync"
    
    def _get_chat_messages_key(self, user_id: str, chat_id: str) -> str:
        """DEPRECATED: Use _get_ai_messages_key() or _get_sync_messages_key() instead"""
        return f"user:{user_id}:chat:{chat_id}:messages:ai"  # Default to AI for backwards compat

    async def add_message_to_chat_history(self, user_id: str, chat_id: str, encrypted_message_json: str, max_history_length: Optional[int] = None) -> bool:
        """Adds an encrypted message (JSON string) to the chat's history (prepends). Optionally trims list."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            await client.lpush(key, encrypted_message_json)
            if max_history_length is not None and max_history_length > 0:
                await client.ltrim(key, 0, max_history_length - 1)
            await client.expire(key, self.CHAT_MESSAGES_TTL)
            return True
        except Exception as e:
            logger.error(f"Error adding message to {key}: {e}")
            return False

    async def get_chat_messages_history(self, user_id: str, chat_id: str, start: int = 0, end: int = -1) -> List[str]:
        """Gets encrypted messages (JSON strings) from chat history. Returns newest first if LPUSHed."""
        client = await self.client
        if not client:
            return []
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            messages_bytes = await client.lrange(key, start, end)
            return [msg.decode('utf-8') for msg in messages_bytes]
        except Exception as e:
            logger.error(f"Error getting messages from {key}: {e}")
            return []

    async def set_chat_messages_history(self, user_id: str, chat_id: str, encrypted_messages_json_list: List[str], ttl: Optional[int] = None) -> bool:
        """Sets the entire message history for a chat. Overwrites existing history."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            await client.delete(key)
            if encrypted_messages_json_list:
                await client.rpush(key, *encrypted_messages_json_list)
            await client.expire(key, ttl if ttl is not None else self.CHAT_MESSAGES_TTL)
            return True
        except Exception as e:
            logger.error(f"Error setting messages for {key}: {e}")
            return False
            
    async def delete_chat_messages_history(self, user_id: str, chat_id: str) -> bool:
        """Deletes the message history for a specific chat."""
        client = await self.client
        if not client:
            return False
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            deleted_count = await client.delete(key)
            return deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting messages for {key}: {e}")
            return False
    
    # ========== SYNC CACHE METHODS (Client-encrypted messages for client sync) ==========
    
    async def set_sync_messages_history(self, user_id: str, chat_id: str, encrypted_messages_json_list: List[str], ttl: int = 3600) -> bool:
        """
        Sets the entire sync message history for a chat (client-encrypted, from Directus).
        Used by cache warming to prepare messages for Phase 1/2/3 sync.
        Default TTL: 1 hour (cleared after successful sync).
        """
        client = await self.client
        if not client:
            return False
        key = self._get_sync_messages_key(user_id, chat_id)
        try:
            await client.delete(key)
            if encrypted_messages_json_list:
                await client.rpush(key, *encrypted_messages_json_list)
            await client.expire(key, ttl)
            logger.debug(f"Set {len(encrypted_messages_json_list)} sync messages for chat {chat_id} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Error setting sync messages for {key}: {e}")
            return False
    
    async def append_sync_message_to_history(self, user_id: str, chat_id: str, encrypted_message_json: str, ttl: int = 3600) -> bool:
        """
        Appends a single client-encrypted message to the sync cache (atomically-ish).
        Used by persistence tasks to ensure messages are available for other devices.
        
        CRITICAL: Checks for duplicates by message ID before appending to prevent
        double messages in client history after login.
        """
        client = await self.client
        if not client:
            return False
        key = self._get_sync_messages_key(user_id, chat_id)
        try:
            # 1. Parse incoming message to get ID
            import json
            try:
                new_msg = json.loads(encrypted_message_json)
                new_msg_id = new_msg.get("id") or new_msg.get("message_id")
            except Exception:
                logger.error("Failed to parse encrypted_message_json for duplicate check")
                new_msg_id = None

            if new_msg_id:
                # 2. Get existing history to check for duplicates
                # Note: For small history (e.g. 100 msgs), LRANGE is fast enough
                existing_msgs_bytes = await client.lrange(key, 0, -1)
                for msg_bytes in existing_msgs_bytes:
                    try:
                        existing_msg = json.loads(msg_bytes.decode('utf-8'))
                        existing_id = existing_msg.get("id") or existing_msg.get("message_id")
                        if existing_id == new_msg_id:
                            logger.info(f"[SYNC_CACHE] ⏭️ Message {new_msg_id} already in sync cache for chat {chat_id}, skipping duplicate append.")
                            return True # Consider successful as it's already there
                    except Exception:
                        continue

            # 3. Use RPUSH to append to the end of the list (chronological order)
            await client.rpush(key, encrypted_message_json)
            # Ensure TTL is refreshed or set if new
            await client.expire(key, ttl)
            logger.debug(f"Appended message {new_msg_id} to sync cache for chat {chat_id} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Error appending sync message to {key}: {e}")
            return False
    
    async def get_sync_messages_history(self, user_id: str, chat_id: str, start: int = 0, end: int = -1) -> List[str]:
        """
        Gets client-encrypted messages (JSON strings) from sync cache.
        Used by Phase 1/2/3 sync handlers to send messages to client.
        """
        client = await self.client
        if not client:
            return []
        key = self._get_sync_messages_key(user_id, chat_id)
        try:
            messages_bytes = await client.lrange(key, start, end)
            messages = [msg.decode('utf-8') for msg in messages_bytes]
            logger.debug(f"Retrieved {len(messages)} sync messages for chat {chat_id}")
            return messages
        except Exception as e:
            logger.error(f"Error getting sync messages from {key}: {e}")
            return []
    
    async def delete_sync_messages_history(self, user_id: str, chat_id: str) -> bool:
        """Deletes the sync message history for a specific chat."""
        client = await self.client
        if not client:
            return False
        key = self._get_sync_messages_key(user_id, chat_id)
        try:
            deleted_count = await client.delete(key)
            logger.debug(f"Deleted sync messages for chat {chat_id}")
            return deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting sync messages for {key}: {e}")
            return False
    
    async def clear_all_sync_messages_for_user(self, user_id: str) -> int:
        """
        Clears all sync message caches for a user after successful Phase 3 sync.
        Returns count of deleted keys.
        """
        client = await self.client
        if not client:
            return 0
        try:
            pattern = f"user:{user_id}:chat:*:messages:sync"
            cursor = 0
            deleted_count = 0
            
            # Use SCAN to find all matching keys (safer than KEYS)
            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted_count += await client.delete(*keys)
                if cursor == 0:
                    break
            
            logger.info(f"Cleared {deleted_count} sync message caches for user {user_id[:8]}...")
            return deleted_count
        except Exception as e:
            logger.error(f"Error clearing sync messages for user {user_id[:8]}...: {e}")
            return 0
    
    async def remove_message_from_cache(self, user_id: str, chat_id: str, client_message_id: str) -> bool:
        """
        Removes a single message (by client_message_id) from both the AI cache and sync cache lists.
        Since Redis lists don't support efficient random-access removal by field value,
        we read the full list, filter out the matching message, and rewrite.
        """
        import json as _json
        removed_any = False

        for key_fn, label in [
            (self._get_chat_messages_key, "AI"),
            (self._get_sync_messages_key, "sync"),
        ]:
            key = key_fn(user_id, chat_id)
            try:
                client = await self.client
                if not client:
                    continue

                # Read all messages from the list
                messages_bytes = await client.lrange(key, 0, -1)
                if not messages_bytes:
                    continue

                # Filter out the message with matching client_message_id
                filtered = []
                found = False
                for msg_bytes in messages_bytes:
                    try:
                        msg = _json.loads(msg_bytes.decode('utf-8'))
                        msg_id = msg.get("client_message_id") or msg.get("message_id") or msg.get("id")
                        if msg_id == client_message_id:
                            found = True
                            continue  # Skip this message (delete it)
                    except Exception:
                        pass
                    filtered.append(msg_bytes.decode('utf-8') if isinstance(msg_bytes, bytes) else msg_bytes)

                if found:
                    # Get current TTL before rewriting
                    ttl = await client.ttl(key)
                    if ttl < 0:
                        ttl = 3600  # Default 1h if no TTL set

                    # Rewrite the list without the deleted message
                    await client.delete(key)
                    if filtered:
                        await client.rpush(key, *filtered)
                        await client.expire(key, ttl)
                    removed_any = True
                    logger.info(f"Removed message {client_message_id} from {label} cache for chat {chat_id}")
                else:
                    logger.debug(f"Message {client_message_id} not found in {label} cache for chat {chat_id}")
            except Exception as e:
                logger.error(f"Error removing message {client_message_id} from {label} cache for chat {chat_id}: {e}")

        return removed_any

    # ========== AI CACHE METHODS (Vault-encrypted messages for AI inference) ==========
    
    async def add_ai_message_to_history(self, user_id: str, chat_id: str, encrypted_message_json: str, max_history_length: int = 500) -> bool:
        """
        Adds a vault-encrypted message to AI inference cache (prepends).
        Used by message_received_handler.py when storing new messages for AI context.
        Automatically limits to last 500 messages per chat to support 120k token context windows.
        Token-based truncation is applied at inference time (preprocessor/main_processor).
        Also enforces TOP_N_MESSAGES_COUNT limit (LRU eviction of oldest chats).
        """
        client = await self.client
        if not client:
            return False
        key = self._get_ai_messages_key(user_id, chat_id)
        try:
            await client.lpush(key, encrypted_message_json)
            if max_history_length > 0:
                await client.ltrim(key, 0, max_history_length - 1)
            await client.expire(key, self.CHAT_MESSAGES_TTL)  # 72 hours
            logger.debug(f"Added AI message to cache for chat {chat_id}")

            # Track activity and enforce LRU limit (TOP_N_MESSAGES_COUNT)
            await self._track_ai_cache_activity(user_id, chat_id)

            return True
        except Exception as e:
            logger.error(f"Error adding AI message to {key}: {e}")
            return False
    
    async def get_ai_messages_history(self, user_id: str, chat_id: str, start: int = 0, end: int = -1) -> List[str]:
        """
        Gets vault-encrypted messages (JSON strings) from AI inference cache.
        Used by message_received_handler.py to build AI context.
        """
        client = await self.client
        if not client:
            return []
        key = self._get_ai_messages_key(user_id, chat_id)
        try:
            messages_bytes = await client.lrange(key, start, end)
            messages = [msg.decode('utf-8') for msg in messages_bytes]
            logger.debug(f"Retrieved {len(messages)} AI messages for chat {chat_id}")
            return messages
        except Exception as e:
            logger.error(f"Error getting AI messages from {key}: {e}")
            return []
    
    async def set_ai_messages_history(self, user_id: str, chat_id: str, encrypted_messages_json_list: List[str], ttl: Optional[int] = None) -> bool:
        """
        Sets the entire AI message history for a chat (vault-encrypted).
        Primarily used during AI inference cache warming (last 3 chats).
        Also enforces TOP_N_MESSAGES_COUNT limit (LRU eviction of oldest chats).
        """
        client = await self.client
        if not client:
            return False
        key = self._get_ai_messages_key(user_id, chat_id)
        try:
            await client.delete(key)
            if encrypted_messages_json_list:
                await client.rpush(key, *encrypted_messages_json_list)
            await client.expire(key, ttl if ttl is not None else self.CHAT_MESSAGES_TTL)
            logger.debug(f"Set {len(encrypted_messages_json_list)} AI messages for chat {chat_id}")

            # Track activity and enforce LRU limit (TOP_N_MESSAGES_COUNT)
            await self._track_ai_cache_activity(user_id, chat_id)

            return True
        except Exception as e:
            logger.error(f"Error setting AI messages for {key}: {e}")
            return False

    async def _track_ai_cache_activity(self, user_id: str, chat_id: str) -> None:
        """
        Updates the AI cache LRU sorted set to track which chats have AI cache.
        Score is current timestamp (for LRU ordering).
        Also enforces TOP_N_MESSAGES_COUNT limit by evicting oldest chats and their embeds.
        """
        client = await self.client
        if not client:
            return

        lru_key = self._get_ai_cache_lru_key(user_id)
        try:
            import time
            current_timestamp = time.time()

            # Add/update this chat in the LRU set with current timestamp as score
            await client.zadd(lru_key, {chat_id: current_timestamp})
            await client.expire(lru_key, self.CHAT_MESSAGES_TTL)  # Same TTL as AI cache

            # Check if we need to evict old chats (enforce TOP_N_MESSAGES_COUNT limit)
            total_chats = await client.zcard(lru_key)
            if total_chats > self.TOP_N_MESSAGES_COUNT:
                # Get chats to evict (oldest ones beyond the limit)
                # ZRANGE with scores sorted ascending (oldest first)
                chats_to_evict = await client.zrange(
                    lru_key,
                    0,
                    total_chats - self.TOP_N_MESSAGES_COUNT - 1
                )

                # Get the remaining top N chat IDs (for embed cross-reference checking)
                remaining_chat_ids_bytes = await client.zrange(
                    lru_key,
                    total_chats - self.TOP_N_MESSAGES_COUNT,
                    -1
                )
                remaining_chat_ids = {
                    cid.decode('utf-8') if isinstance(cid, bytes) else cid
                    for cid in remaining_chat_ids_bytes
                }

                for evict_chat_id_bytes in chats_to_evict:
                    evict_chat_id = evict_chat_id_bytes.decode('utf-8') if isinstance(evict_chat_id_bytes, bytes) else evict_chat_id_bytes

                    # Delete the AI cache for this chat
                    ai_cache_key = self._get_ai_messages_key(user_id, evict_chat_id)
                    await client.delete(ai_cache_key)

                    # Evict embeds that are only used by this chat
                    await self._evict_chat_embeds(client, evict_chat_id, remaining_chat_ids)

                    # Remove from LRU tracking
                    await client.zrem(lru_key, evict_chat_id)
                    logger.info(f"[AI_CACHE_LRU] Evicted AI cache for chat {evict_chat_id} (user {user_id[:8]}...) - exceeded TOP_N_MESSAGES_COUNT ({self.TOP_N_MESSAGES_COUNT})")

        except Exception as e:
            logger.error(f"Error tracking AI cache activity for user {user_id[:8]}..., chat {chat_id}: {e}")

    async def _evict_chat_embeds(self, client, evict_chat_id: str, remaining_chat_ids: set) -> None:
        """
        Evicts embeds that are only used by the evicted chat.
        Embeds used in any of the remaining chats are preserved.
        """
        try:
            # Get embed IDs for the evicted chat
            evict_embed_index_key = f"chat:{evict_chat_id}:embed_ids"
            embed_ids_bytes = await client.smembers(evict_embed_index_key)

            if not embed_ids_bytes:
                return

            # Collect embed indices for remaining chats to check cross-references
            remaining_embed_ids: set = set()
            for remaining_chat_id in remaining_chat_ids:
                remaining_index_key = f"chat:{remaining_chat_id}:embed_ids"
                remaining_embeds = await client.smembers(remaining_index_key)
                for embed_id_bytes in remaining_embeds:
                    embed_id = embed_id_bytes.decode('utf-8') if isinstance(embed_id_bytes, bytes) else embed_id_bytes
                    remaining_embed_ids.add(embed_id)

            # Evict embeds not used in remaining chats
            evicted_count = 0
            for embed_id_bytes in embed_ids_bytes:
                embed_id = embed_id_bytes.decode('utf-8') if isinstance(embed_id_bytes, bytes) else embed_id_bytes
                if embed_id not in remaining_embed_ids:
                    # Embed is only used by evicted chat - delete it
                    embed_cache_key = f"embed:{embed_id}"
                    await client.delete(embed_cache_key)
                    evicted_count += 1

            # Delete the embed index for the evicted chat
            await client.delete(evict_embed_index_key)

            if evicted_count > 0:
                logger.info(f"[AI_CACHE_LRU] Evicted {evicted_count} embed(s) for chat {evict_chat_id}")

        except Exception as e:
            logger.error(f"Error evicting embeds for chat {evict_chat_id}: {e}")

    async def delete_ai_messages_history(self, user_id: str, chat_id: str) -> bool:
        """Deletes the AI message history for a chat and removes it from LRU tracking."""
        client = await self.client
        if not client:
            return False
        key = self._get_ai_messages_key(user_id, chat_id)
        lru_key = self._get_ai_cache_lru_key(user_id)
        try:
            await client.delete(key)
            await client.zrem(lru_key, chat_id)
            logger.debug(f"Deleted AI messages history for chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting AI messages for {key}: {e}")
            return False

    async def save_chat_message_and_update_versions(
        self, user_id: str, chat_id: str, message_data: MessageInCache, max_history_length: Optional[int] = None,
        explicit_messages_v: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Serializes a MessageInCache object, adds it to the AI cache (vault-encrypted),
        increments the messages_v (or sets it to explicit_messages_v), and updates the last_edited_overall_timestamp.
        
        This method is ONLY for AI inference cache (vault-encrypted).
        For client sync, use set_sync_messages_history() during cache warming.
        
        Returns a dict with new versions on success, None on failure.
        """
        client = await self.client
        if not client:
            logger.error(f"CACHE_OP_ERROR: Redis client not available. Failed to save message for user {user_id}, chat {chat_id}.")
            return None

        try:
            # 1. Save the vault-encrypted message to AI cache
            message_json_str = message_data.model_dump_json()
            logger.debug(f"CACHE_OP: Serialized vault-encrypted message for user {user_id}, chat {chat_id}, msg_id {message_data.id} to JSON: {message_json_str[:200]}...")

            # Use AI cache method (vault-encrypted, 72h TTL, for AI inference only)
            save_success = await self.add_ai_message_to_history(
                user_id,
                chat_id,
                message_json_str,
                max_history_length=max_history_length if max_history_length is not None else 100
            )
            if not save_success:
                logger.error(f"CACHE_OP_ERROR: Failed to save vault-encrypted message to AI cache for user {user_id}, chat {chat_id}, msg_id {message_data.id}.")
                return None
            logger.debug(f"CACHE_OP_SUCCESS: Successfully saved vault-encrypted message to AI cache for user {user_id}, chat {chat_id}, msg_id {message_data.id}.")

            # 2. Update messages_v in cache
            if explicit_messages_v is not None:
                # Use explicit version (e.g. from Directus update)
                success = await self.set_chat_version_component(user_id, chat_id, "messages_v", explicit_messages_v)
                if not success:
                    logger.error(f"CACHE_OP_ERROR: Failed to set explicit messages_v to {explicit_messages_v} for user {user_id}, chat {chat_id}.")
                    return None
                new_messages_v = explicit_messages_v
                logger.debug(f"CACHE_OP_SUCCESS: Set explicit messages_v to {new_messages_v} for user {user_id}, chat {chat_id}.")
            else:
                # Increment the CACHE version
                new_messages_v = await self.increment_chat_component_version(user_id, chat_id, "messages_v")
                if new_messages_v is None:
                    logger.error(f"CACHE_OP_ERROR: Failed to increment messages_v for user {user_id}, chat {chat_id} after saving message {message_data.id}.")
                    return None
                logger.debug(f"CACHE_OP_SUCCESS: Incremented messages_v to {new_messages_v} for user {user_id}, chat {chat_id}.")
            
            # MESSAGES_V_TRACKING: Log the cache version update
            logger.info(
                f"[MESSAGES_V_TRACKING] CACHE_UPDATE: "
                f"chat_id={chat_id}, "
                f"new_cache_v={new_messages_v}, "
                f"explicit={explicit_messages_v is not None}, "
                f"msg_id={message_data.id}, "
                f"msg_role={message_data.role}, "
                f"source=save_chat_message_and_update_versions"
            )

            # 3. Update last_edited_overall_timestamp
            try:
                # message_data.created_at is already an integer Unix timestamp as per MessageInCache schema
                if not isinstance(message_data.created_at, int):
                    logger.warning(
                        f"CACHE_OP_WARNING: message_data.created_at was expected to be int for chat {chat_id}, msg {message_data.id}, "
                        f"but got {type(message_data.created_at)} with value '{message_data.created_at}'. "
                        f"Falling back to current UTC timestamp."
                    )
                    new_last_edited_overall_timestamp = int(datetime.now(timezone.utc).timestamp())
                else:
                    new_last_edited_overall_timestamp = message_data.created_at
            except Exception as e_ts: # Catch any unexpected error during access or type check
                logger.error(
                    f"CACHE_OP_ERROR: Error processing message_data.created_at ('{message_data.created_at}') "
                    f"for chat {chat_id}, msg {message_data.id}. Error: {e_ts}", exc_info=True
                )
                logger.warning(
                    f"CACHE_OP_WARNING: Falling back to current UTC timestamp for chat {chat_id}, msg {message_data.id} due to an unexpected error."
                )
                new_last_edited_overall_timestamp = int(datetime.now(timezone.utc).timestamp())

            score_update_success = await self.update_chat_score_in_ids_versions(
                user_id, chat_id, new_last_edited_overall_timestamp
            )
            if not score_update_success:
                logger.error(f"CACHE_OP_ERROR: Failed to update last_edited_overall_timestamp for user {user_id}, chat {chat_id} to {new_last_edited_overall_timestamp}.")
                # Potentially consider rollback or cleanup.
                return None
            logger.debug(f"CACHE_OP_SUCCESS: Updated last_edited_overall_timestamp to {new_last_edited_overall_timestamp} for user {user_id}, chat {chat_id}.")

            return {
                "messages_v": new_messages_v,
                "last_edited_overall_timestamp": new_last_edited_overall_timestamp
            }

        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: General error in save_chat_message_and_update_versions for user {user_id}, chat {chat_id}, msg_id {message_data.id}: {e}", exc_info=True)
            return None

    # Message Queue Methods for AI Processing
    def _get_chat_queue_key(self, chat_id: str) -> str:
        """Returns the cache key for queued messages for a chat."""
        return f"chat:{chat_id}:message_queue"
    
    def _get_active_task_key(self, chat_id: str) -> str:
        """Returns the cache key for tracking active AI task for a chat."""
        return f"chat:{chat_id}:active_ai_task"
    
    def _get_task_chat_mapping_key(self, task_id: str) -> str:
        """Returns the cache key for mapping a task_id back to its chat_id (for cancellation ownership)."""
        return f"active_task:{task_id}:chat_id"
    
    async def set_active_ai_task(self, chat_id: str, task_id: str, ttl: int = 600) -> bool:
        """
        Mark a chat as having an active AI task and store reverse mapping for ownership.
        
        Args:
            chat_id: The chat ID
            task_id: The Celery task ID
            ttl: Time to live in seconds (default: 10 minutes, should be longer than any task)
        
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.error("Redis client not available for set_active_ai_task")
            return False
        
        key = self._get_active_task_key(chat_id)
        reverse_key = self._get_task_chat_mapping_key(task_id)
        try:
            # Store chat -> task mapping
            await client.set(key, task_id, ex=ttl)
            # Store task -> chat mapping (reverse mapping)
            await client.set(reverse_key, chat_id, ex=ttl)
            
            logger.debug(f"Set active AI task {task_id} for chat {chat_id} (and reverse mapping)")
            return True
        except Exception as e:
            logger.error(f"Error setting active AI task for chat {chat_id}: {e}", exc_info=True)
            return False
    
    async def get_active_ai_task(self, chat_id: str) -> Optional[str]:
        """
        Get the active AI task ID for a chat, if any.
        
        Args:
            chat_id: The chat ID
        
        Returns:
            Task ID if active task exists, None otherwise
        """
        client = await self.client
        if not client:
            return None
        
        key = self._get_active_task_key(chat_id)
        try:
            task_id = await client.get(key)
            return task_id.decode('utf-8') if task_id else None
        except Exception as e:
            logger.error(f"Error getting active AI task for chat {chat_id}: {e}", exc_info=True)
            return None

    async def get_chat_id_for_task(self, task_id: str) -> Optional[str]:
        """
        Get the chat ID associated with an active AI task.
        
        Args:
            task_id: The task ID
            
        Returns:
            Chat ID if found, None otherwise
        """
        client = await self.client
        if not client:
            return None
        
        key = self._get_task_chat_mapping_key(task_id)
        try:
            chat_id = await client.get(key)
            return chat_id.decode('utf-8') if chat_id else None
        except Exception as e:
            logger.error(f"Error getting chat ID for task {task_id}: {e}", exc_info=True)
            return None
    
    async def clear_active_ai_task(self, chat_id: str) -> bool:
        """
        Clear the active AI task marker for a chat and its reverse mapping.
        
        Args:
            chat_id: The chat ID
        
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            return False
        
        key = self._get_active_task_key(chat_id)
        try:
            # We need to find the task_id to clear the reverse mapping
            task_id_bytes = await client.get(key)
            if task_id_bytes:
                task_id = task_id_bytes.decode('utf-8')
                reverse_key = self._get_task_chat_mapping_key(task_id)
                await client.delete(reverse_key)
            
            await client.delete(key)
            logger.debug(f"Cleared active AI task for chat {chat_id} (and reverse mapping)")
            return True
        except Exception as e:
            logger.error(f"Error clearing active AI task for chat {chat_id}: {e}", exc_info=True)
            return False
    
    async def queue_message(self, chat_id: str, message_data: Dict[str, Any], ttl: int = 600) -> bool:
        """
        Add a message to the queue for a chat.
        Multiple messages will be combined when processed.
        
        Args:
            chat_id: The chat ID
            message_data: The message data to queue (should match AskSkillRequestSchema structure)
            ttl: Time to live in seconds (default: 10 minutes)
        
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.error("Redis client not available for queue_message")
            return False
        
        key = self._get_chat_queue_key(chat_id)
        try:
            import json
            # Use Redis list to store queued messages
            message_json = json.dumps(message_data)
            await client.rpush(key, message_json)
            await client.expire(key, ttl)  # Set TTL on the list
            queue_length = await client.llen(key)
            logger.info(f"Queued message for chat {chat_id}. Queue length: {queue_length}")
            return True
        except Exception as e:
            logger.error(f"Error queueing message for chat {chat_id}: {e}", exc_info=True)
            return False
    
    async def get_queued_messages(self, chat_id: str) -> List[Dict[str, Any]]:
        """
        Get all queued messages for a chat and clear the queue.
        Messages are returned in order and then removed from the queue.
        
        Args:
            chat_id: The chat ID
        
        Returns:
            List of queued message dictionaries
        """
        client = await self.client
        if not client:
            return []
        
        key = self._get_chat_queue_key(chat_id)
        try:
            import json
            # Get all messages from the list
            messages_json = await client.lrange(key, 0, -1)
            if not messages_json:
                return []
            
            # Parse messages
            messages = []
            for msg_json in messages_json:
                try:
                    messages.append(json.loads(msg_json.decode('utf-8')))
                except Exception as e:
                    logger.warning(f"Error parsing queued message: {e}")
            
            # Clear the queue after retrieving
            await client.delete(key)
            logger.info(f"Retrieved and cleared {len(messages)} queued messages for chat {chat_id}")
            return messages
        except Exception as e:
            logger.error(f"Error getting queued messages for chat {chat_id}: {e}", exc_info=True)
            return []
    
    # Embed caching methods
    def _get_embed_cache_key(self, embed_id: str) -> str:
        """Returns the cache key for an embed (global cache, one entry per embed)."""
        return f"embed:{embed_id}"
    
    def _get_chat_embed_ids_key(self, chat_id: str) -> str:
        """Returns the cache key for tracking embed IDs in a chat (for eviction)."""
        return f"chat:{chat_id}:embed_ids"
    
    async def get_embed_from_cache(self, embed_id: str) -> Optional[Dict[str, Any]]:
        """
        Get an embed from cache by embed_id.
        
        Args:
            embed_id: The embed identifier
            
        Returns:
            Embed dictionary if found, None otherwise
        """
        client = await self.client
        if not client:
            return None
        
        key = self._get_embed_cache_key(embed_id)
        try:
            import json
            embed_json = await client.get(key)
            if embed_json:
                embed_data = json.loads(embed_json.decode('utf-8'))
                logger.debug(f"Cache HIT: Retrieved embed {embed_id} from cache")
                return embed_data
            else:
                logger.debug(f"Cache MISS: Embed {embed_id} not in cache")
                return None
        except Exception as e:
            logger.error(f"Error getting embed {embed_id} from cache: {e}", exc_info=True)
            return None
    
    async def set_embed_in_cache(
        self,
        embed_id: str,
        embed_data: Dict[str, Any],
        chat_id: str,
        ttl: int = 86400  # 24 hours, same as message cache
    ) -> bool:
        """
        Cache an embed with vault encryption.
        
        Args:
            embed_id: The embed identifier
            embed_data: Embed data dictionary (should already be vault-encrypted)
            chat_id: Chat ID for indexing (for eviction tracking)
            ttl: Time to live in seconds (default: 24 hours)
            
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.warning(f"Redis client not available, skipping embed cache for {embed_id}")
            return False
        
        key = self._get_embed_cache_key(embed_id)
        try:
            import json
            embed_json = json.dumps(embed_data)
            await client.set(key, embed_json, ex=ttl)
            
            # Add to chat index for eviction tracking
            chat_embed_index_key = self._get_chat_embed_ids_key(chat_id)
            await client.sadd(chat_embed_index_key, embed_id)
            await client.expire(chat_embed_index_key, ttl)
            
            logger.debug(f"Cached embed {embed_id} at {key} with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching embed {embed_id}: {e}", exc_info=True)
            return False
    
    async def get_chat_embed_ids(self, chat_id: str) -> List[str]:
        """
        Get all embed IDs for a chat (for eviction tracking).
        
        Args:
            chat_id: The chat ID
            
        Returns:
            List of embed IDs
        """
        client = await self.client
        if not client:
            return []
        
        key = self._get_chat_embed_ids_key(chat_id)
        try:
            embed_ids_bytes = await client.smembers(key)
            embed_ids = [embed_id.decode('utf-8') for embed_id in embed_ids_bytes]
            logger.debug(f"Retrieved {len(embed_ids)} embed IDs for chat {chat_id}")
            return embed_ids
        except Exception as e:
            logger.error(f"Error getting embed IDs for chat {chat_id}: {e}", exc_info=True)
            return []
    
    async def add_embed_id_to_chat_index(self, chat_id: str, embed_id: str, ttl: int = 3600) -> bool:
        """
        Add an embed_id to the chat's embed index (for sync cache tracking).
        
        Args:
            chat_id: The chat ID
            embed_id: The embed ID to add
            ttl: Time to live for the index key in seconds (default: 1 hour)
            
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            return False
        
        key = self._get_chat_embed_ids_key(chat_id)
        try:
            await client.sadd(key, embed_id)
            await client.expire(key, ttl)
            logger.debug(f"Added embed {embed_id} to chat index {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding embed {embed_id} to chat index {chat_id}: {e}", exc_info=True)
            return False
    
    async def delete_chat_embed_cache(self, chat_id: str) -> int:
        """
        Delete all cached embeds for a chat and the embed index.
        
        This should be called when a chat is deleted to clean up all embed caches
        associated with that chat. It removes:
        1. All individual embed cache entries (embed:{embed_id})
        2. The chat's embed index (chat:{chat_id}:embed_ids)
        
        Args:
            chat_id: The chat ID whose embeds should be cleared
            
        Returns:
            Number of embed cache entries deleted (not including the index)
        """
        client = await self.client
        if not client:
            logger.warning(f"Redis client not available, cannot delete embed cache for chat {chat_id}")
            return 0
        
        chat_embed_index_key = self._get_chat_embed_ids_key(chat_id)
        deleted_count = 0
        
        try:
            # Get all embed IDs from the chat's index
            embed_ids_bytes = await client.smembers(chat_embed_index_key)
            
            if embed_ids_bytes:
                # Delete each embed's cache entry
                for embed_id_bytes in embed_ids_bytes:
                    embed_id = embed_id_bytes.decode('utf-8') if isinstance(embed_id_bytes, bytes) else embed_id_bytes
                    embed_key = self._get_embed_cache_key(embed_id)
                    try:
                        result = await client.delete(embed_key)
                        if result:
                            deleted_count += 1
                            logger.debug(f"Deleted embed cache: {embed_key}")
                    except Exception as embed_delete_error:
                        logger.warning(f"Failed to delete embed cache {embed_key}: {embed_delete_error}")
                
                logger.info(f"Deleted {deleted_count} embed cache entries for chat {chat_id}")
            else:
                logger.debug(f"No embed IDs found in index for chat {chat_id}")
            
            # Always attempt to delete the index key itself
            await client.delete(chat_embed_index_key)
            logger.debug(f"Deleted chat embed index key: {chat_embed_index_key}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error deleting embed cache for chat {chat_id}: {e}", exc_info=True)
            return deleted_count
    
    async def get_sync_embeds_for_chat(self, chat_id: str) -> List[Dict[str, Any]]:
        """
        Get all embeds from sync cache for a chat.
        
        Embeds in sync cache are stored with key pattern: embed:{embed_id}:sync
        The chat's embed index (chat:{chat_id}:embed_ids) tracks which embeds belong to the chat.
        
        Args:
            chat_id: The chat ID
            
        Returns:
            List of embed data dictionaries (client-encrypted)
        """
        client = await self.client
        if not client:
            return []
        
        try:
            import json
            
            # Get embed IDs from chat index
            embed_ids = await self.get_chat_embed_ids(chat_id)
            if not embed_ids:
                logger.debug(f"No embeds indexed for chat {chat_id}")
                return []
            
            # Fetch each embed from sync cache
            embeds = []
            for embed_id in embed_ids:
                sync_key = f"embed:{embed_id}:sync"
                embed_json = await client.get(sync_key)
                if embed_json:
                    try:
                        embed_data = json.loads(embed_json.decode('utf-8') if isinstance(embed_json, bytes) else embed_json)
                        embeds.append(embed_data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse embed {embed_id} from sync cache: {e}")
                else:
                    logger.debug(f"Embed {embed_id} not found in sync cache (may have expired)")
            
            logger.info(f"Retrieved {len(embeds)} embeds from sync cache for chat {chat_id}")
            return embeds
        except Exception as e:
            logger.error(f"Error getting sync embeds for chat {chat_id}: {e}", exc_info=True)
            return []
    
    # ========== App Settings and Memories Cache Methods ==========
    
    def _get_app_settings_memories_cache_key(self, user_id: str, chat_id: str, app_id: str, item_key: str) -> str:
        """
        Returns the cache key for an app settings/memories entry.
        
        Format: chat:{chat_id}:app_settings_memories:{app_id}:{item_key}
        
        Note: Chat-specific so that app settings/memories are automatically evicted
        when the chat is evicted from cache.
        
        Args:
            user_id: User ID (for logging/debugging, not used in key)
            chat_id: Chat ID (required for chat-specific caching)
            app_id: App ID
            item_key: Settings/memories item key (category name)
            
        Returns:
            Cache key string
        """
        return f"chat:{chat_id}:app_settings_memories:{app_id}:{item_key}"
    
    def _get_chat_app_settings_memories_index_key(self, chat_id: str) -> str:
        """
        Returns the cache key for tracking all app settings/memories keys for a chat.
        
        Format: chat:{chat_id}:app_settings_memories_keys
        
        Args:
            chat_id: Chat ID
            
        Returns:
            Cache key string
        """
        return f"chat:{chat_id}:app_settings_memories_keys"
    
    async def get_app_settings_memories_from_cache(
        self,
        user_id: str,
        chat_id: str,
        app_id: str,
        item_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get app settings/memories entry from cache.
        
        Args:
            user_id: User ID (for logging)
            chat_id: Chat ID (required for chat-specific caching)
            app_id: App ID
            item_key: Settings/memories item key (category name)
            
        Returns:
            App settings/memories data dictionary if found, None otherwise
        """
        client = await self.client
        if not client:
            return None
        
        key = self._get_app_settings_memories_cache_key(user_id, chat_id, app_id, item_key)
        try:
            import json
            cached_data = await client.get(key)
            if cached_data:
                data = json.loads(cached_data.decode('utf-8'))
                logger.debug(f"Cache HIT: Retrieved app settings/memories {app_id}:{item_key} for chat {chat_id}")
                return data
            else:
                logger.debug(f"Cache MISS: App settings/memories {app_id}:{item_key} not in cache for chat {chat_id}")
                return None
        except Exception as e:
            logger.error(f"Error getting app settings/memories {app_id}:{item_key} from cache: {e}", exc_info=True)
            return None
    
    async def set_app_settings_memories_in_cache(
        self,
        user_id: str,
        chat_id: str,
        app_id: str,
        item_key: str,
        data: Dict[str, Any],
        ttl: int = 86400  # 24 hours, same as message cache
    ) -> bool:
        """
        Cache app settings/memories entry with vault encryption.
        
        Chat-specific caching ensures app settings/memories are automatically evicted
        when the chat is evicted from cache.
        
        Args:
            user_id: User ID (for logging)
            chat_id: Chat ID (required for chat-specific caching)
            app_id: App ID
            item_key: Settings/memories item key (category name)
            data: App settings/memories data dictionary (should already be vault-encrypted)
            ttl: Time to live in seconds (default: 24 hours)
            
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.warning(f"Redis client not available, skipping app settings/memories cache for {app_id}:{item_key}")
            return False
        
        key = self._get_app_settings_memories_cache_key(user_id, chat_id, app_id, item_key)
        try:
            import json
            data_json = json.dumps(data)
            await client.set(key, data_json, ex=ttl)
            
            # Add to chat index for tracking (enables batch deletion when chat is evicted)
            index_key = self._get_chat_app_settings_memories_index_key(chat_id)
            entry_key = f"{app_id}:{item_key}"
            await client.sadd(index_key, entry_key)
            await client.expire(index_key, ttl)
            
            logger.debug(f"Cached app settings/memories {app_id}:{item_key} for chat {chat_id} at {key} with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching app settings/memories {app_id}:{item_key}: {e}", exc_info=True)
            return False
    
    async def get_chat_app_settings_memories_keys(self, chat_id: str) -> List[str]:
        """
        Get all app settings/memories keys for a chat (format: "app_id:item_key").
        
        Args:
            chat_id: Chat ID
            
        Returns:
            List of keys in "app_id:item_key" format
        """
        client = await self.client
        if not client:
            return []
        
        index_key = self._get_chat_app_settings_memories_index_key(chat_id)
        try:
            keys_bytes = await client.smembers(index_key)
            keys = [key.decode('utf-8') for key in keys_bytes]
            logger.debug(f"Retrieved {len(keys)} app settings/memories keys for chat {chat_id}")
            return keys
        except Exception as e:
            logger.error(f"Error getting app settings/memories keys for chat {chat_id}: {e}", exc_info=True)
            return []
    
    async def delete_chat_app_settings_memories(self, user_id: str, chat_id: str) -> int:
        """
        Delete all app settings/memories entries for a chat.
        
        This is called when a chat is evicted from cache to ensure
        sensitive app settings/memories are also removed.
        
        Args:
            user_id: User ID (for logging)
            chat_id: Chat ID
            
        Returns:
            Number of entries deleted
        """
        client = await self.client
        if not client:
            return 0
        
        try:
            # Get all keys for this chat
            keys = await self.get_chat_app_settings_memories_keys(chat_id)
            
            if not keys:
                logger.debug(f"No app settings/memories to delete for chat {chat_id}")
                return 0
            
            # Delete all entries
            deleted_count = 0
            for key_str in keys:
                try:
                    # Parse "app_id:item_key" format
                    parts = key_str.split(":", 1)
                    if len(parts) != 2:
                        continue
                    
                    app_id, item_key = parts
                    cache_key = self._get_app_settings_memories_cache_key(user_id, chat_id, app_id, item_key)
                    result = await client.delete(cache_key)
                    if result:
                        deleted_count += 1
                except Exception as e:
                    logger.error(f"Error deleting app settings/memories {key_str} for chat {chat_id}: {e}", exc_info=True)
                    continue
            
            # Delete the index
            index_key = self._get_chat_app_settings_memories_index_key(chat_id)
            await client.delete(index_key)
            
            logger.info(f"Deleted {deleted_count} app settings/memories entries for chat {chat_id}")
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting app settings/memories for chat {chat_id}: {e}", exc_info=True)
            return 0
    
    async def get_app_settings_memories_batch_from_cache(
        self,
        user_id: str,
        chat_id: str,
        requested_keys: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple app settings/memories entries from cache in batch.
        
        Args:
            user_id: User ID (for logging)
            chat_id: Chat ID (required for chat-specific caching)
            requested_keys: List of keys in "app_id:item_key" format
            
        Returns:
            Dictionary mapping "app_id:item_key" to data (only includes found entries)
        """
        result = {}
        
        # DEBUG: Log all requested keys
        logger.info(f"[DEBUG] get_app_settings_memories_batch_from_cache called with requested_keys={requested_keys} for chat {chat_id}")
        
        for key_str in requested_keys:
            try:
                # Parse "app_id:item_key" format
                parts = key_str.split(":", 1)
                if len(parts) != 2:
                    logger.warning(f"Invalid app settings/memories key format: {key_str}")
                    continue
                
                app_id, item_key = parts
                logger.info(f"[DEBUG] Looking up cache key: app_id={app_id!r}, item_key={item_key!r} for chat {chat_id}")
                data = await self.get_app_settings_memories_from_cache(user_id, chat_id, app_id, item_key)
                if data:
                    result[key_str] = data
            except Exception as e:
                logger.error(f"Error getting app settings/memories {key_str} from cache: {e}", exc_info=True)
                continue
        
        logger.debug(f"Retrieved {len(result)}/{len(requested_keys)} app settings/memories entries from cache for chat {chat_id}")
        return result
    
    # === Pending App Settings/Memories Request Methods ===
    # These methods manage the pending request context that allows
    # re-triggering AI processing when user confirms/rejects the request.
    
    def _get_pending_app_settings_memories_request_key(self, chat_id: str) -> str:
        """Get Redis key for pending app settings/memories request context."""
        return f"pending_app_settings_memories_request:{chat_id}"
    
    async def store_pending_app_settings_memories_request(
        self,
        chat_id: str,
        context: Dict[str, Any],
        ttl: int = 86400 * 7  # 7 days default
    ) -> bool:
        """
        Store pending app settings/memories request context.
        
        When the AI needs app settings/memories that aren't in cache, we store
        the request context so we can re-trigger processing when user confirms/rejects.
        
        NOTE: We store MINIMAL context - NOT the message_history!
        The chat history is already cached on the server (recent chats are cached).
        When continuing, we retrieve the chat from cache using get_chat_messages().
        
        NOTE: The per-user index was removed because permission request persistence
        is now handled client-side via encrypted system messages in chat history.
        The client (ChatHistory.svelte) detects "unpaired" requests and re-shows
        the dialog automatically after session recovery.
        
        Args:
            chat_id: Chat ID
            context: MINIMAL request context needed to re-trigger processing:
                - request_id: The app settings/memories request ID
                - chat_id: Chat ID
                - message_id: Original user message ID
                - user_id: User ID
                - user_id_hash: Hashed user ID
                - mate_id: Selected mate ID (if any)
                - active_focus_id: Active focus ID (if any)
                - chat_has_title: Whether chat has a title
                - is_incognito: Whether chat is incognito
                - requested_keys: Keys that were requested
                - task_id: Original task ID (for logging)
                
                NOT INCLUDED (retrieved from chat cache when continuing):
                - message_history
                - message_content
            ttl: Time to live in seconds (default: 7 days)
            
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.warning(f"Redis client not available, skipping pending request storage for chat {chat_id}")
            return False
        
        key = self._get_pending_app_settings_memories_request_key(chat_id)
        try:
            import json
            context_json = json.dumps(context)
            await client.set(key, context_json, ex=ttl)
            
            logger.info(f"Stored pending app settings/memories request context for chat {chat_id} with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error storing pending app settings/memories request for chat {chat_id}: {e}", exc_info=True)
            return False
    
    async def get_pending_app_settings_memories_request(
        self,
        chat_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get pending app settings/memories request context.
        
        Args:
            chat_id: Chat ID
            
        Returns:
            Request context dictionary if found, None otherwise
        """
        client = await self.client
        if not client:
            return None
        
        key = self._get_pending_app_settings_memories_request_key(chat_id)
        try:
            import json
            data = await client.get(key)
            if data:
                context = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
                logger.debug(f"Retrieved pending app settings/memories request context for chat {chat_id}")
                return context
            return None
        except Exception as e:
            logger.error(f"Error getting pending app settings/memories request for chat {chat_id}: {e}", exc_info=True)
            return None
    
    async def delete_pending_app_settings_memories_request(
        self,
        chat_id: str,
        user_id: str = None
    ) -> bool:
        """
        Delete pending app settings/memories request context.
        
        Called after the request has been processed (user confirmed/rejected).
        
        Args:
            chat_id: Chat ID
            user_id: User ID (kept for API compatibility, no longer used for index cleanup)
            
        Returns:
            True if deleted (or didn't exist), False on error
        """
        client = await self.client
        if not client:
            return False
        
        key = self._get_pending_app_settings_memories_request_key(chat_id)
        try:
            await client.delete(key)
            logger.debug(f"Deleted pending app settings/memories request context for chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting pending app settings/memories request for chat {chat_id}: {e}", exc_info=True)
            return False