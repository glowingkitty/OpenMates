import logging
import json
import time
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_DEVICES = 10 # Maximum number of device hashes to store per user

async def add_user_device_hash(
    self, # Assuming this is part of a class like DirectusService
    user_id: str,
    device_hash: str
) -> Tuple[bool, str]:
    """
    Adds a new device hash to a user's 'connected_devices' list in Directus.
    If the hash already exists, it does nothing.
    Prunes old hashes if the list exceeds MAX_DEVICES.
    Prioritizes writing to cache first, then Directus.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.
        device_hash: The new device hash to add.

    Returns:
        Tuple[bool, str]: Success status and a message.
    """
    try:
        # 1. Get user data to retrieve existing connected_devices (try cache first)
        user_data_from_cache = await self.cache.get_user_by_id(user_id)
        connected_devices: List[str] = []
        needs_directus_fetch = True

        if user_data_from_cache:
            connected_devices_raw_from_cache = user_data_from_cache.get("connected_devices")
            if connected_devices_raw_from_cache is not None:
                if isinstance(connected_devices_raw_from_cache, list):
                    connected_devices = connected_devices_raw_from_cache
                    needs_directus_fetch = False
                    logger.debug(f"Retrieved connected_devices (list from cache) for user {user_id[:6]}...")
                else:
                    try:
                        parsed_devices = json.loads(connected_devices_raw_from_cache)
                        if isinstance(parsed_devices, list):
                            connected_devices = parsed_devices
                            needs_directus_fetch = False # Found in cache, no need to fetch from Directus
                            logger.debug(f"Retrieved connected_devices (parsed from cache) for user {user_id[:6]}...")
                        else:
                            logger.warning(f"Cached connected_devices for user {user_id[:6]} is not a list after parsing. Fetching from Directus.")
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode cached connected_devices JSON for user {user_id[:6]}. Fetching from Directus.")
                    except Exception as e:
                        logger.warning(f"Error processing cached connected_devices for user {user_id[:6]}: {str(e)}. Fetching from Directus.")
        
        if needs_directus_fetch:
            user_url = f"{self.base_url}/users/{user_id}"
            get_response = await self._make_api_request("GET", user_url, params={"fields": "connected_devices"})

            if get_response.status_code != 200:
                logger.error(f"Failed to retrieve user {user_id} for device hash update: {get_response.status_code} {get_response.text}")
                return False, f"Failed to retrieve user: {get_response.status_code}"

            user_data_from_directus = get_response.json().get("data", {})
            connected_devices_raw_from_directus = user_data_from_directus.get("connected_devices")

            if connected_devices_raw_from_directus is not None:
                if isinstance(connected_devices_raw_from_directus, list):
                    connected_devices = connected_devices_raw_from_directus
                    logger.debug(f"Retrieved connected_devices (list from Directus) for user {user_id[:6]}...")
                else:
                    try:
                        parsed_devices = json.loads(connected_devices_raw_from_directus)
                        if isinstance(parsed_devices, list):
                            connected_devices = parsed_devices
                            logger.debug(f"Retrieved connected_devices (parsed from Directus) for user {user_id[:6]}...")
                        else:
                            logger.warning(f"Directus connected_devices for user {user_id[:6]} is not a list after parsing. Starting with empty list.")
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode Directus connected_devices JSON for user {user_id[:6]}. Starting with empty list.")
                    except Exception as e:
                        logger.error(f"Error processing Directus connected_devices for user {user_id[:6]}: {str(e)}. Starting with empty list.")
            else:
                logger.debug(f"No connected_devices found in Directus for user {user_id[:6]}. Starting with empty list.")

        initial_connected_devices_count = len(connected_devices)
        needs_update = False

        if device_hash not in connected_devices:
            # Add new device hash
            logger.info(f"Adding new device hash {device_hash[:8]}... for user {user_id}")
            connected_devices.append(device_hash)
            needs_update = True
        else:
            logger.debug(f"Device hash {device_hash[:8]}... already known for user {user_id}. No update needed.")

        # 2. Prune old devices if exceeding MAX_DEVICES
        if len(connected_devices) > MAX_DEVICES:
            logger.info(f"Device hash count ({len(connected_devices)}) exceeds limit ({MAX_DEVICES}) for user {user_id}. Pruning...")
            # Keep only the MAX_DEVICES most recent devices (assuming append adds to end)
            connected_devices = connected_devices[-MAX_DEVICES:]
            needs_update = True # Ensure update happens if pruning occurred

        # 3. Update cache first if changes were made
        if needs_update:
            logger.debug(f"Updating connected_devices in cache for user {user_id}")
            try:
                # Update cache first
                await self.cache.update_user(user_id, {"connected_devices": json.dumps(connected_devices)})
                logger.info(f"Successfully updated connected_devices in cache for user {user_id[:6]}...")

                # Then update Directus
                user_url = f"{self.base_url}/users/{user_id}" # Ensure user_url is defined
                update_payload = {"connected_devices": json.dumps(connected_devices)}
                patch_response = await self._make_api_request(
                    "PATCH", user_url, json=update_payload
                )

                if patch_response.status_code == 200:
                    logger.info(f"Successfully updated connected_devices in Directus for user {user_id}")
                    return True, "Device information updated successfully"
                else:
                    logger.error(f"Failed to update connected_devices in Directus for user {user_id}: {patch_response.status_code} {patch_response.text}")
                    return False, f"Failed to update device info: {patch_response.status_code}"
            except Exception as e:
                 logger.error(f"Error updating connected_devices for user {user_id}: {str(e)}", exc_info=True)
                 return False, f"Error updating devices: {str(e)}"
        else:
            return True, "Device information is up to date"

    except Exception as e:
        error_msg = f"Unexpected error adding device hash for user {user_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


async def get_user_device_hashes(
    self, # Assuming this is part of a class like DirectusService
    user_id: str
) -> List[str]:
    """
    Retrieves the list of known device hashes for a user.
    Prioritizes fetching from cache, falls back to Directus.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.

    Returns:
        List[str]: A list of device hashes, or an empty list if none are found or an error occurs.
    """
    connected_devices: List[str] = []
    needs_directus_fetch = True

    try:
        # 1. Try to get from cache first
        user_data_from_cache = await self.cache.get_user_by_id(user_id)
        if user_data_from_cache:
            connected_devices_raw_from_cache = user_data_from_cache.get("connected_devices")
            if connected_devices_raw_from_cache is not None:
                if isinstance(connected_devices_raw_from_cache, list):
                    connected_devices = connected_devices_raw_from_cache
                    needs_directus_fetch = False # Found in cache, no need to fetch from Directus
                    logger.debug(f"Retrieved connected_devices (list from cache) for user {user_id[:6]}...")
                else:
                    try:
                        parsed_devices = json.loads(connected_devices_raw_from_cache)
                        if isinstance(parsed_devices, list):
                            connected_devices = parsed_devices
                            needs_directus_fetch = False # Found in cache, no need to fetch from Directus
                            logger.debug(f"Retrieved connected_devices (parsed from cache) for user {user_id[:6]}...")
                        else:
                            logger.warning(f"Cached connected_devices for user {user_id[:6]} is not a list after parsing. Falling back to Directus.")
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode cached connected_devices JSON for user {user_id[:6]}. Falling back to Directus.")
                    except Exception as e:
                        logger.warning(f"Error processing cached connected_devices for user {user_id[:6]}: {str(e)}. Falling back to Directus.")
        
        # 2. If not found in cache or cache data was invalid, fetch from Directus
        if needs_directus_fetch:
            user_url = f"{self.base_url}/users/{user_id}"
            get_response = await self._make_api_request("GET", user_url, params={"fields": "connected_devices"})

            if get_response.status_code != 200:
                logger.warning(f"Failed to retrieve user {user_id} from Directus for device hash check: {get_response.status_code}")
                return [] # Return empty list on Directus fetch failure

            user_data_from_directus = get_response.json().get("data", {})
            connected_devices_raw_from_directus = user_data_from_directus.get("connected_devices")

            if connected_devices_raw_from_directus is not None:
                if isinstance(connected_devices_raw_from_directus, list):
                    connected_devices = connected_devices_raw_from_directus
                    logger.debug(f"Retrieved connected_devices (list from Directus) for user {user_id[:6]}...")
                    # Update cache with the data fetched from Directus
                    await self.cache.update_user(user_id, {"connected_devices": json.dumps(connected_devices)})
                    logger.debug(f"Updated connected_devices in cache for user {user_id[:6]} after Directus fetch.")
                else:
                    try:
                        parsed_devices = json.loads(connected_devices_raw_from_directus)
                        if isinstance(parsed_devices, list):
                            connected_devices = parsed_devices
                            logger.debug(f"Retrieved connected_devices (parsed from Directus) for user {user_id[:6]}...")
                            # Update cache with the data fetched from Directus
                            await self.cache.update_user(user_id, {"connected_devices": json.dumps(connected_devices)})
                            logger.debug(f"Updated connected_devices in cache for user {user_id[:6]} after Directus fetch.")
                        else:
                            logger.warning(f"Directus connected_devices for user {user_id[:6]} is not a list after parsing. Returning empty list.")
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode Directus connected_devices JSON for user {user_id[:6]}. Returning empty list.")
                    except Exception as e:
                        logger.error(f"Error processing Directus connected_devices for user {user_id[:6]}: {str(e)}. Returning empty list.")
            else:
                logger.debug(f"No connected_devices found in Directus for user {user_id[:6]}. Returning empty list.")

    except Exception as e:
        logger.error(f"Unexpected error retrieving user device hashes for user {user_id}: {str(e)}", exc_info=True)
        return []

    return connected_devices

# Removed: update_user_device_record (replaced by add_user_device_hash)
# Removed: get_stored_device_data (replaced by get_user_device_hashes)
