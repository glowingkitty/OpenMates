import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

class DeviceCacheMixin:
    """Mixin for device-specific caching methods"""

    def _get_user_device_key(self, user_id: str, stable_hash: str) -> str:
        """Helper to generate the cache key for a specific user device."""
        return f"{self.USER_DEVICE_KEY_PREFIX}{user_id}:{stable_hash}"

    async def get_user_device_data(self, user_id: str, stable_hash: str) -> Optional[Dict[str, Any]]:
        """Get device data from cache and deserialize it."""
        key = self._get_user_device_key(user_id, stable_hash)
        logger.debug(f"Cache GET for device data: Key '{key}'")
        try:
            raw_data = await self.get(key)
            if not raw_data:
                logger.debug(f"No device data found in cache for key '{key}'.")
                return None

            logger.debug(f"Raw device data retrieved from cache for key '{key}': {raw_data}")

            if isinstance(raw_data, dict):
                logger.debug(f"Device data for key '{key}' is already a dict. Returning directly.")
                return raw_data
            
            if isinstance(raw_data, str):
                logger.debug(f"Device data for key '{key}' is a string. Attempting to deserialize from JSON.")
                deserialized_data = json.loads(raw_data)
                logger.debug(f"Successfully deserialized device data for key '{key}'.")
                return deserialized_data

            logger.warning(f"Device data for key '{key}' is of unexpected type: {type(raw_data)}. Returning None.")
            return None

        except json.JSONDecodeError as e:
            logger.error(f"Cache JSON DECODE error for device key '{key}': {e}. Raw data: '{raw_data}'", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Cache GET error for device key '{key}': {e}", exc_info=True)
            return None

    async def set_user_device_data(
        self, user_id: str, stable_hash: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """Caches device data by serializing it to JSON."""
        key = self._get_user_device_key(user_id, stable_hash)
        final_ttl = ttl if ttl is not None else self.USER_DEVICE_TTL
        logger.debug(f"Cache SET for device data: Key '{key}', TTL: {final_ttl}s")
        try:
            serialized_data = json.dumps(data)
            logger.debug(f"Serialized device data for key '{key}': {serialized_data}")
            return await self.set(key, serialized_data, ttl=final_ttl)
        except TypeError as e:
            logger.error(f"Cache SET serialization error for device key '{key}': {e}. Data: {data}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Cache SET error for device key '{key}': {e}", exc_info=True)
            return False

    async def delete_user_device_data(self, user_id: str, stable_hash: str) -> bool:
        """Deletes a specific device from cache."""
        key = self._get_user_device_key(user_id, stable_hash)
        return await self.delete(key)
