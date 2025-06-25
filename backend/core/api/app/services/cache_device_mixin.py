import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class DeviceCacheMixin:
    """Mixin for device-specific caching methods"""

    def _get_user_device_key(self, user_id: str, stable_hash: str) -> str:
        """Helper to generate the cache key for a specific user device."""
        return f"{self.USER_DEVICE_KEY_PREFIX}{user_id}:{stable_hash}"

    async def get_user_device_data(self, user_id: str, stable_hash: str) -> Optional[Dict[str, Any]]:
        """Get device data from cache."""
        key = self._get_user_device_key(user_id, stable_hash)
        logger.debug(f"Cache GET for device data: Key '{key}'")
        try:
            return await self.get(key)
        except Exception as e:
            logger.error(f"Cache GET error for device key '{key}': {e}", exc_info=True)
            return None

    async def set_user_device_data(
        self, user_id: str, stable_hash: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """Caches device data."""
        key = self._get_user_device_key(user_id, stable_hash)
        final_ttl = ttl if ttl is not None else self.USER_DEVICE_TTL
        logger.debug(f"Cache SET for device data: Key '{key}', TTL: {final_ttl}s")
        try:
            return await self.set(key, data, ttl=final_ttl)
        except Exception as e:
            logger.error(f"Cache SET error for device key '{key}': {e}", exc_info=True)
            return False

    async def delete_user_device_data(self, user_id: str, stable_hash: str) -> bool:
        """Deletes a specific device from cache."""
        key = self._get_user_device_key(user_id, stable_hash)
        return await self.delete(key)
