import logging
import hashlib
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class UserCacheMixin:
    """Mixin for user-specific caching methods"""

    async def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user data from cache by user ID"""
        try:
            cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            logger.debug(f"Attempting cache GET for user ID: {user_id} (Key: '{cache_key}')")
            return await self.get(cache_key)
        except Exception as e:
            logger.error(f"Error getting user from cache by ID '{user_id}': {str(e)}")
            return None

    async def get_user_vault_key_id(self, user_id: str) -> Optional[str]:
        """
        Get user's vault_key_id from cache.
        Returns None if user not in cache or vault_key_id not set.
        """
        try:
            user_data = await self.get_user_by_id(user_id)
            if not user_data or not isinstance(user_data, dict):
                logger.debug(f"No cached user data found for user {user_id}")
                return None
            
            vault_key_id = user_data.get("vault_key_id")
            if vault_key_id:
                logger.debug(f"Retrieved vault_key_id from cache for user {user_id}")
            else:
                logger.debug(f"User {user_id} in cache but no vault_key_id found")
            
            return vault_key_id
        except Exception as e:
            logger.error(f"Error getting vault_key_id from cache for user '{user_id}': {str(e)}")
            return None

    async def get_user_timezone(self, user_id: str) -> Optional[str]:
        """
        Get user's timezone from cache.
        Returns None if user not in cache or timezone not set.
        The timezone is in IANA format (e.g., 'Europe/Berlin', 'America/New_York').
        """
        try:
            user_data = await self.get_user_by_id(user_id)
            if not user_data or not isinstance(user_data, dict):
                logger.debug(f"No cached user data found for user {user_id}")
                return None
            
            timezone = user_data.get("timezone")
            if timezone:
                logger.debug(f"Retrieved timezone '{timezone}' from cache for user {user_id}")
            else:
                logger.debug(f"User {user_id} in cache but no timezone found")
            
            return timezone
        except Exception as e:
            logger.error(f"Error getting timezone from cache for user '{user_id}': {str(e)}")
            return None

    async def get_user_by_token(self, refresh_token: str) -> Optional[Dict]:
        """Get user data from cache by refresh token."""
        try:
            if not refresh_token:
                logger.debug("Attempted cache GET by token: No token provided.")
                return None

            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            session_cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
            logger.debug(f"Attempting cache GET for user_id by token hash: {token_hash[:8]}... (Key: '{session_cache_key}')")

            user_id_data = await self.get(session_cache_key)

            user_id = None
            if isinstance(user_id_data, dict):
                user_id = user_id_data.get("user_id")
            elif isinstance(user_id_data, str):
                 user_id = user_id_data

            if not user_id:
                logger.debug(f"Cache MISS for user_id associated with token hash {token_hash[:8]}...")
                return None

            logger.debug(f"Cache HIT for user_id '{user_id}' associated with token hash {token_hash[:8]}...")
            return await self.get_user_by_id(user_id)
        except Exception as e:
            logger.error(f"Error getting user from cache by token hash {token_hash[:8]}...: {str(e)}")
            return None

    # Auth-critical fields that must never be silently clobbered by a partial cache write.
    # If the incoming user_data is missing any of these but the existing cached entry has them,
    # the existing values are preserved. This prevents billing/payment/session code paths
    # (which may write partial dicts) from wiping fields required for passkey login.
    _PROTECTED_PROFILE_FIELDS = (
        "encrypted_email_with_master_key",
        "encrypted_email_address",
        "hashed_email",
        "user_email_salt",
        "vault_key_id",
        "vault_key_version",
        "encrypted_settings",
        "lookup_hashes",
    )

    async def set_user(self, user_data: Dict, user_id: str = None, refresh_token: str = None, ttl: Optional[int] = None) -> bool:
        """Cache user data by user_id and optionally associate a refresh token."""
        try:
            if not user_data:
                logger.warning("Attempted to cache empty user data.")
                return False

            user_id = user_id or user_data.get("user_id") or user_data.get("id")
            if not user_id:
                logger.error("Cannot cache user data: no user_id provided or found in user_data.")
                return False

            # CRITICAL: Ensure user_id is always present in user_data for WebSocket authentication
            # WebSocket auth checks for user_id in the cached data, so it must be present
            if "user_id" not in user_data:
                user_data["user_id"] = user_id
            # Also ensure "id" is present for compatibility
            if "id" not in user_data:
                user_data["id"] = user_id

            logger.debug(f"Attempting cache SET for user ID: {user_id}")
            user_ttl = ttl if ttl is not None else self.USER_TTL
            session_ttl = ttl if ttl is not None else self.SESSION_TTL

            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"

            # Guard: prevent partial writes from clobbering auth-critical fields.
            # Many callers (billing, payments, session refresh) write back user_data dicts
            # that may not contain passkey/encryption fields. If the existing cached profile
            # has these fields, carry them forward so passkey login keeps working.
            existing = await self.get(user_cache_key)
            if existing and isinstance(existing, dict):
                preserved = []
                for field in self._PROTECTED_PROFILE_FIELDS:
                    old_val = existing.get(field)
                    new_val = user_data.get(field)
                    if old_val and not new_val:
                        user_data[field] = old_val
                        preserved.append(field)
                if preserved:
                    logger.info(
                        f"set_user: preserved {len(preserved)} protected field(s) from existing cache "
                        f"for user {user_id[:8]}...: {preserved}"
                    )

            user_set_success = await self.set(user_cache_key, user_data, ttl=user_ttl)
            logger.debug(f"Cache SET result for user key '{user_cache_key}': {user_set_success}")

            session_set_success = True
            if refresh_token:
                logger.debug(f"Attempting cache SET for session token link to user ID: {user_id}")
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                session_cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
                session_link_data = {"user_id": user_id}
                session_set_success = await self.set(session_cache_key, session_link_data, ttl=session_ttl)
                logger.debug(f"Cache SET result for session link key '{session_cache_key}': {session_set_success}")

            return user_set_success
        except Exception as e:
            logger.error(f"Error caching user data for user '{user_id}': {str(e)}")
            return False

    async def update_user(self, user_id: str, updated_fields: Dict) -> bool:
        """
        Update specific fields of cached user data.
        Preserves the existing key TTL so that partial updates (e.g. last_online_timestamp)
        do not reset a stay_logged_in user's 30-day cache back to the default 24-hour USER_TTL.
        """
        try:
            if not user_id or not updated_fields:
                logger.warning("Update user cache skipped: missing user_id or updated_fields.")
                return False

            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            logger.debug(f"Attempting cache UPDATE for user ID: {user_id} (Key: '{user_cache_key}')")

            # Read existing TTL BEFORE the get+set cycle so we can preserve it.
            # This prevents resetting a 30-day stay_logged_in session to 24h on every
            # /session call that updates last_online_timestamp or last_session_country.
            existing_ttl = await self.get_key_ttl(user_cache_key)

            current_data = await self.get(user_cache_key)

            if not current_data or not isinstance(current_data, dict):
                logger.warning(f"Cannot update user cache: no existing data found or data is not a dict for user '{user_id}' (Key: '{user_cache_key}')")
                return False

            logger.debug(f"Updating fields for user '{user_id}': {list(updated_fields.keys())}")
            current_data.update(updated_fields)

            # Use the existing TTL if the key has one (> 0), otherwise fall back to USER_TTL.
            # existing_ttl: -2 = key gone, -1 = no expiry, >0 = seconds remaining.
            ttl_to_use = existing_ttl if existing_ttl > 0 else self.USER_TTL
            user_update_success = await self.set(user_cache_key, current_data, ttl=ttl_to_use)
            logger.debug(f"Cache SET result for user key '{user_cache_key}' after update: {user_update_success} (ttl={ttl_to_use}s, preserved from existing={existing_ttl}s)")

            return user_update_success
        except Exception as e:
            logger.error(f"Error updating cached user data for user '{user_id}': {str(e)}")
            return False

    async def delete_user_cache(self, user_id: str) -> bool:
        """Remove user from cache (all related entries)."""
        try:
            if not user_id:
                return False

            logger.debug(f"Attempting cache DELETE for all data related to user ID: {user_id}")

            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            delete_user_success = await self.delete(user_cache_key)
            logger.debug(f"Cache DELETE result for user key '{user_cache_key}': {delete_user_success}")

            device_pattern = f"{self.USER_DEVICE_KEY_PREFIX}{user_id}:*"
            logger.debug(f"Searching for device keys with pattern: '{device_pattern}'")
            device_keys = await self.get_keys_by_pattern(device_pattern)
            logger.debug(f"Found {len(device_keys)} device keys to delete.")
            devices_deleted_count = 0
            for key in device_keys:
                delete_device_success = await self.delete(key)
                if delete_device_success:
                    devices_deleted_count += 1
                logger.debug(f"Cache DELETE result for device key '{key}': {delete_device_success}")
            logger.debug(f"Finished deleting device caches for user {user_id}. Deleted {devices_deleted_count} keys.")

            session_pattern = f"{self.SESSION_KEY_PREFIX}*"
            logger.debug(f"Searching for session keys with pattern: '{session_pattern}'")
            session_keys = await self.get_keys_by_pattern(session_pattern)
            logger.debug(f"Found {len(session_keys)} potential session keys to check.")
            sessions_deleted_count = 0
            for key in session_keys:
                session_link_data = await self.get(key)
                linked_user_id = None
                if isinstance(session_link_data, dict):
                    linked_user_id = session_link_data.get("user_id")
                elif isinstance(session_link_data, str):
                    linked_user_id = session_link_data

                if linked_user_id == user_id:
                    logger.debug(f"Deleting session link cache for key '{key}' (User: {user_id})")
                    delete_session_success = await self.delete(key)
                    if delete_session_success:
                        sessions_deleted_count += 1
                    logger.debug(f"Cache DELETE result for session link key '{key}': {delete_session_success}")
            logger.debug(f"Finished deleting session link caches for user {user_id}. Deleted {sessions_deleted_count} keys.")

            # --- Chat & embed cache cleanup for this user ---
            # Gather chat_ids from the user's sorted set (if cache was primed)
            chat_ids = await self.get_chat_ids_versions(user_id, with_scores=False)
            logger.debug(f"Chat cleanup for user {user_id}: found {len(chat_ids)} chat_ids in cache.")

            for chat_id in chat_ids:
                try:
                    # Delete chat versions hash
                    await self.delete_chat_versions(user_id, chat_id)
                    # Delete list item data (title/icon/category/draft metadata)
                    await self.delete_chat_list_item_data(user_id, chat_id)
                    # Delete message history caches (ai + sync)
                    await self.delete_chat_messages_history(user_id, chat_id)
                    await self.delete_sync_messages_history(user_id, chat_id)
                    # Delete app settings/memories cache for the chat (per-chat)
                    await self.delete_chat_app_settings_memories(user_id, chat_id)

                    # Remove embed caches linked to this chat
                    chat_embed_index_key = f"chat:{chat_id}:embed_ids"
                    embed_ids = await self.get_keys_by_pattern(chat_embed_index_key)
                    # get_keys_by_pattern returns list of keys; if present, fetch members
                    if embed_ids:
                        # embed_ids here are actually keys; fetch members from the set
                        client = await self.client
                        if client:
                            members = await client.smembers(chat_embed_index_key)
                            if members:
                                for embed_id in members:
                                    embed_key = f"embed:{embed_id.decode('utf-8') if isinstance(embed_id, bytes) else embed_id}"
                                    await self.delete(embed_key)
                            await client.delete(chat_embed_index_key)
                    else:
                        # If no key, continue silently
                        pass

                except Exception as chat_cleanup_error:
                    logger.error(f"Error cleaning chat cache for user {user_id}, chat {chat_id}: {chat_cleanup_error}", exc_info=True)

            # Remove top-level chat ids set last
            user_chat_ids_key = self._get_user_chat_ids_versions_key(user_id)
            await self.delete(user_chat_ids_key)

            return delete_user_success
        except Exception as e:
            logger.error(f"Error deleting cached user data for user '{user_id}': {str(e)}")
            return False

    async def delete_user_sessions(self, user_id: str) -> bool:
        """
        Delete only session tokens for a user (invalidates all active sessions).
        Used during account recovery to force re-login with new credentials.
        Unlike delete_user_cache, this preserves other cached data.
        
        Args:
            user_id: The user's UUID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not user_id:
                return False
            
            logger.debug(f"Attempting to delete all sessions for user ID: {user_id}")
            
            # Find and delete all session tokens for this user
            session_pattern = f"{self.SESSION_KEY_PREFIX}*"
            session_keys = await self.get_keys_by_pattern(session_pattern)
            
            sessions_deleted_count = 0
            for key in session_keys:
                session_link_data = await self.get(key)
                linked_user_id = None
                
                if isinstance(session_link_data, dict):
                    linked_user_id = session_link_data.get("user_id")
                elif isinstance(session_link_data, str):
                    linked_user_id = session_link_data
                
                if linked_user_id == user_id:
                    delete_success = await self.delete(key)
                    if delete_success:
                        sessions_deleted_count += 1
                    logger.debug(f"Deleted session key '{key}' for user {user_id[:8]}...")
            
            logger.info(f"Deleted {sessions_deleted_count} sessions for user {user_id[:8]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting sessions for user '{user_id}': {str(e)}", exc_info=True)
            return False

    # --- User App Settings and Memories Caching Methods (Combined) ---

    def _get_user_app_settings_and_memories_key(self, user_id_hash: str, app_id: str, item_key: str) -> str:
        """Helper to generate the cache key for a specific user app setting or memory item."""
        return f"{self.USER_APP_SETTINGS_AND_MEMORIES_KEY_PREFIX}{user_id_hash}:{app_id}:{item_key}"

    async def set_user_app_settings_and_memories_item(
        self, user_id_hash: str, app_id: str, item_key: str, encrypted_value_json: str, ttl: Optional[int] = None
    ) -> bool:
        """Caches an encrypted user app setting or memory item value (JSON string)."""
        key = self._get_user_app_settings_and_memories_key(user_id_hash, app_id, item_key)
        final_ttl = ttl if ttl is not None else self.USER_APP_DATA_TTL
        logger.debug(f"Cache SET for user app data item: Key '{key}', TTL: {final_ttl}s")
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache SET skipped for key '{key}': client not connected.")
                return False
            await client.setex(key, final_ttl, encrypted_value_json)
            return True
        except Exception as e:
            logger.error(f"Cache SET error for user app data item key '{key}': {str(e)}")
            return False

    async def get_user_app_settings_and_memories_item(
        self, user_id_hash: str, app_id: str, item_key: str, refresh_ttl: bool = True
    ) -> Optional[str]:
        """Gets an encrypted user app setting or memory item value (JSON string) from cache. Optionally refreshes TTL."""
        key = self._get_user_app_settings_and_memories_key(user_id_hash, app_id, item_key)
        logger.debug(f"Cache GET for user app data item: Key '{key}'")
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache GET skipped for key '{key}': client not connected.")
                return None
            
            encrypted_value_bytes = await client.get(key)
            if not encrypted_value_bytes:
                logger.debug(f"Cache MISS for user app data item key: '{key}'")
                return None

            encrypted_value_json = encrypted_value_bytes.decode('utf-8')
            logger.debug(f"Cache HIT for user app data item key: '{key}'")
            
            if refresh_ttl:
                final_ttl = self.USER_APP_DATA_TTL
                logger.debug(f"Refreshing TTL for user app data item key '{key}' to {final_ttl}s")
                await client.expire(key, final_ttl)
            return encrypted_value_json
        except Exception as e:
            logger.error(f"Cache GET error for user app data item key '{key}': {str(e)}")
            return None

    async def delete_user_app_settings_and_memories_item(self, user_id_hash: str, app_id: str, item_key: str) -> bool:
        """Deletes a specific user app setting or memory item from cache."""
        key = self._get_user_app_settings_and_memories_key(user_id_hash, app_id, item_key)
        return await self.delete(key) # self.delete already logs

    async def delete_all_user_app_settings_and_memories_for_app(self, user_id_hash: str, app_id: str) -> int:
        """Deletes all app settings and memories for a specific app of a user. Returns count of deleted keys."""
        pattern = f"{self.USER_APP_SETTINGS_AND_MEMORIES_KEY_PREFIX}{user_id_hash}:{app_id}:*"
        keys_to_delete = await self.get_keys_by_pattern(pattern)
        deleted_count = 0
        if keys_to_delete:
            for key in keys_to_delete:
                if await self.delete(key):
                    deleted_count += 1
        logger.info(f"Deleted {deleted_count} app settings/memories keys for user '{user_id_hash}', app '{app_id}'.")
        return deleted_count

    async def delete_all_user_app_settings_and_memories(self, user_id_hash: str) -> int:
        """Deletes all app settings and memories for a user. Returns count of deleted keys."""
        pattern = f"{self.USER_APP_SETTINGS_AND_MEMORIES_KEY_PREFIX}{user_id_hash}:*"
        keys_to_delete = await self.get_keys_by_pattern(pattern)
        deleted_count = 0
        if keys_to_delete:
            for key in keys_to_delete:
                if await self.delete(key):
                    deleted_count += 1
        logger.info(f"Deleted {deleted_count} app settings/memories keys for user '{user_id_hash}'.")
        return deleted_count

    # --- End of User App Settings and Memories Caching Methods ---
