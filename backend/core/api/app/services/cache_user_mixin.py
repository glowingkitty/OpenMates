import logging
import hashlib
from typing import Optional, Dict, Any

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

            logger.debug(f"Attempting cache SET for user ID: {user_id}")
            user_ttl = ttl if ttl is not None else self.USER_TTL
            session_ttl = ttl if ttl is not None else self.SESSION_TTL

            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
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
        """Update specific fields of cached user data."""
        try:
            if not user_id or not updated_fields:
                logger.warning("Update user cache skipped: missing user_id or updated_fields.")
                return False

            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            logger.debug(f"Attempting cache UPDATE for user ID: {user_id} (Key: '{user_cache_key}')")
            current_data = await self.get(user_cache_key)

            if not current_data or not isinstance(current_data, dict):
                logger.warning(f"Cannot update user cache: no existing data found or data is not a dict for user '{user_id}' (Key: '{user_cache_key}')")
                return False

            logger.debug(f"Updating fields for user '{user_id}': {list(updated_fields.keys())}")
            current_data.update(updated_fields)

            user_update_success = await self.set(user_cache_key, current_data, ttl=self.USER_TTL)
            logger.debug(f"Cache SET result for user key '{user_cache_key}' after update: {user_update_success}")

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

            return delete_user_success
        except Exception as e:
            logger.error(f"Error deleting cached user data for user '{user_id}': {str(e)}")
            return False