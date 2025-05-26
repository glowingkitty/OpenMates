import logging
import json
import time
from typing import Tuple, Dict, Any, Optional # Added Dict, Any, Optional
from typing import Tuple

logger = logging.getLogger(__name__)

from backend.core.api.app.utils.device_fingerprint import DeviceFingerprint

# Define fields to store in Directus for each device hash
# These should align with fields used in calculate_stable_hash and calculate_risk_level
STORED_FINGERPRINT_FIELDS = [
    "user_agent", "accept_language", "browser_name", "browser_version",
    "os_name", "os_version", "device_type", "country_code",
    "screen_hash", "time_zone_hash", "language_hash", "canvas_hash", "webgl_hash"
    # Add other client hashes if implemented, e.g., "installed_fonts_hash"
]

MAX_DEVICES = 10 # Maximum number of devices to store per user

async def update_user_device_record(
    self, # Assuming this is part of a class like DirectusService
    user_id: str,
    current_fingerprint: DeviceFingerprint
) -> Tuple[bool, str]:
    """
    Updates a user's device records in Directus using the stable hash.
    - Retrieves and decrypts existing device records.
    - Calculates the stable hash for the current fingerprint.
    - Adds or updates the record for the stable hash with relevant fingerprint data.
    - Prunes old devices if exceeding MAX_DEVICES.
    - Re-encrypts and stores back in Directus if changes were made.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.
        current_fingerprint: The DeviceFingerprint object for the current device.

    Returns:
        Tuple[bool, str]: Success status and a message.
    """
    try:
        # 1. Get user data (including encrypted devices and vault key)
        user_url = f"{self.base_url}/users/{user_id}" # Removed ?fields=...
        get_response = await self._make_api_request("GET", user_url)

        if get_response.status_code != 200:
            logger.error(f"Failed to retrieve user {user_id} for device update: {get_response.status_code} {get_response.text}")
            return False, f"Failed to retrieve user: {get_response.status_code}"

        user_data = get_response.json().get("data", {})
        vault_key_id = user_data.get("vault_key_id")
        encrypted_devices_str = user_data.get("encrypted_devices")

        if not vault_key_id:
            logger.error(f"User {user_id} has no vault_key_id for device update.")
            return False, "User has no encryption key"

        # 2. Decrypt existing device records
        device_records: Dict[str, Dict[str, Any]] = {} # {stable_hash: {fingerprint_data}}
        if encrypted_devices_str:
            try:
                decrypted_devices_json = await self.encryption_service.decrypt_with_user_key(
                    encrypted_devices_str, vault_key_id
                )
                device_records = json.loads(decrypted_devices_json)
                if not isinstance(device_records, dict):
                     logger.warning(f"Decrypted devices for user {user_id} is not a dict: {type(device_records)}. Resetting.")
                     device_records = {}
            except json.JSONDecodeError:
                 logger.error(f"Failed to decode decrypted devices JSON for user {user_id}. Content: '{decrypted_devices_json[:100]}...'")
                 device_records = {} # Start fresh if decryption or decoding fails
            except Exception as e:
                logger.error(f"Error decrypting devices for user {user_id}: {str(e)}", exc_info=True)
                device_records = {} # Start fresh

        # 3. Process current fingerprint
        current_stable_hash = current_fingerprint.calculate_stable_hash()
        current_time = int(time.time())
        needs_update = False

        # Prepare data to store for the current fingerprint
        current_device_data_to_store = {
            field: getattr(current_fingerprint, field, None)
            for field in STORED_FINGERPRINT_FIELDS
        }
        # Filter out None values from the data to be stored
        current_device_data_to_store = {k: v for k, v in current_device_data_to_store.items() if v is not None}


        if current_stable_hash in device_records:
            # Update last_seen timestamp for existing device record
            # Only trigger an update if it hasn't been seen very recently (e.g., > 1 min)
            # to reduce unnecessary writes during rapid requests.
            if (current_time - device_records[current_stable_hash].get("last_seen", 0)) > 60:
                 device_records[current_stable_hash]["last_seen"] = current_time
                 # Optionally update stored fields if they differ? For now, just update timestamp.
                 # If we want to update fields:
                 # existing_data = device_records[current_stable_hash]
                 # for key, value in current_device_data_to_store.items():
                 #     if existing_data.get(key) != value:
                 #         existing_data[key] = value
                 #         needs_update = True
                 # if needs_update: # If fields were updated
                 #     existing_data["last_seen"] = current_time

                 needs_update = True # Mark for update just for timestamp change
            else:
                 logger.debug(f"Device hash {current_stable_hash[:8]}... seen recently for user {user_id}. Skipping timestamp update.")

        else:
            # Add new device record
            logger.info(f"Adding new device hash {current_stable_hash[:8]}... for user {user_id}")
            device_records[current_stable_hash] = {
                **current_device_data_to_store, # Store the filtered relevant fields
                "first_seen": current_time,
                "last_seen": current_time
            }
            needs_update = True

        # 4. Prune old devices if exceeding MAX_DEVICES
        if len(device_records) > MAX_DEVICES:
            logger.info(f"Device count ({len(device_records)}) exceeds limit ({MAX_DEVICES}) for user {user_id}. Pruning...")
            # Sort devices by 'last_seen' timestamp (oldest first)
            # Items are (stable_hash, data_dict)
            sorted_devices = sorted(device_records.items(), key=lambda item: item[1].get('last_seen', 0))

            # Keep only the MAX_DEVICES most recent devices
            device_records = dict(sorted_devices[-MAX_DEVICES:])
            needs_update = True # Ensure update happens if pruning occurred

        # 5. Re-encrypt and update Directus if changes were made
        if needs_update:
            logger.debug(f"Updating device records in Directus for user {user_id}")
            try:
                updated_devices_json = json.dumps(device_records)
                encrypted_devices, _ = await self.encryption_service.encrypt_with_user_key(
                    updated_devices_json, vault_key_id
                )

                update_payload = {"encrypted_devices": encrypted_devices}
                patch_response = await self._make_api_request(
                    "PATCH", user_url, json=update_payload
                )

                if patch_response.status_code == 200:
                    logger.info(f"Successfully updated device records for user {user_id}")
                    return True, "Device information updated successfully"
                else:
                    logger.error(f"Failed to update device info for user {user_id}: {patch_response.status_code} {patch_response.text}")
                    return False, f"Failed to update device info: {patch_response.status_code}"
            except Exception as e:
                 logger.error(f"Error encrypting/updating devices for user {user_id}: {str(e)}", exc_info=True)
                 return False, f"Error encrypting/updating devices: {str(e)}"
        else:
            logger.debug(f"No device record changes needed for user {user_id}")
            return True, "Device information is up to date"

    except Exception as e:
        error_msg = f"Unexpected error updating device info for user {user_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


async def get_stored_device_data(
    self, # Assuming this is part of a class like DirectusService
    user_id: str,
    stable_hash_to_check: str
) -> Optional[Dict[str, Any]]:
    """
    Retrieves the stored fingerprint data for a specific stable hash for a user.
    - Gets user profile (potentially cached).
    - Decrypts device records if necessary (might need direct user fetch if not in profile cache).
    - Returns the dictionary of stored data for the given hash, or None if not found.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.
        stable_hash_to_check: The stable fingerprint hash to look for.

    Returns:
        Optional[Dict[str, Any]]: The stored data for the device hash, or None.
    """
    try:
        # Option 1: Try getting from cached profile first (if profile includes decrypted devices)
        # success, profile, _ = await self.get_user_profile(user_id) # Assumes get_user_profile decrypts devices
        # if success and profile and "devices" in profile and isinstance(profile["devices"], dict):
        #     return profile["devices"].get(stable_hash_to_check)

        # Option 2: Fetch user directly, decrypt devices (more reliable but less performant if profile isn't cached)
        user_url = f"{self.base_url}/users/{user_id}" # Removed ?fields=...
        get_response = await self._make_api_request("GET", user_url)

        if get_response.status_code != 200:
            logger.warning(f"Failed to retrieve user {user_id} for device check: {get_response.status_code}")
            return None

        user_data = get_response.json().get("data", {})
        vault_key_id = user_data.get("vault_key_id")
        encrypted_devices_str = user_data.get("encrypted_devices")

        if not vault_key_id or not encrypted_devices_str:
            # logger.debug(f"User {user_id} has no key or no devices stored.")
            return None # No devices stored or no key to decrypt

        # Decrypt
        try:
            decrypted_devices_json = await self.encryption_service.decrypt_with_user_key(
                encrypted_devices_str, vault_key_id
            )
            device_records = json.loads(decrypted_devices_json)
            if isinstance(device_records, dict):
                 # logger.debug(f"Found {len(device_records)} device records for user {user_id}. Checking for hash {stable_hash_to_check[:8]}...")
                 return device_records.get(stable_hash_to_check) # Return data if hash exists, else None
            else:
                 logger.warning(f"Decrypted devices for user {user_id} is not a dict during check. Type: {type(device_records)}")
                 return None
        except Exception as e:
            logger.error(f"Error decrypting/checking devices for user {user_id}: {str(e)}", exc_info=True)
            return None

    except Exception as e:
        logger.error(f"Unexpected error checking user device {stable_hash_to_check[:8]} for user {user_id}: {str(e)}", exc_info=True)
        return None

# --- Replace existing functions ---
# The logic from the old update_user_device and check_user_device is now
# incorporated into update_user_device_record and get_stored_device_data.
# We need to remove or comment out the old functions.
