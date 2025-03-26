import logging
import json
import time
from typing import Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def update_user_device(self, user_id: str, device_fingerprint: str, device_location: str) -> Tuple[bool, str]:
    """
    Update a user's device information in Directus
    - Retrieves and decrypts existing devices
    - Adds or updates the device info
    - Re-encrypts and stores back in Directus
    """
    try:
        # Get the user first to retrieve encrypted_devices and vault key
        url = f"{self.base_url}/users/{user_id}"
        response = await self._make_api_request("GET", url)
        
        if response.status_code != 200:
            return False, f"Failed to retrieve user: {response.status_code}"
            
        user_data = response.json().get("data", {})
        vault_key_id = user_data.get("vault_key_id")
        encrypted_devices_str = user_data.get("encrypted_devices")
        
        if not vault_key_id:
            return False, "User has no encryption key"
            
        # If user has existing encrypted devices, decrypt them
        devices_dict = {}
        if encrypted_devices_str:
            try:
                decrypted_devices = await self.encryption_service.decrypt_with_user_key(
                    encrypted_devices_str, vault_key_id
                )
                devices_dict = json.loads(decrypted_devices)
            except Exception as e:
                logger.error(f"Error decrypting devices: {str(e)}")
                # Continue with empty dict if we can't decrypt
                devices_dict = {}
        
        # Get current time for updating
        current_time = int(time.time())
        
        needs_update = False
        if device_fingerprint in devices_dict:
            # For existing devices: Keep existing location, only update timestamp
            last_update = devices_dict[device_fingerprint].get("recent", 0)
            if (current_time - last_update) > 3600:  # 1 hour
                devices_dict[device_fingerprint]["recent"] = current_time
                needs_update = True
        else:
            # For new devices: Add with provided location data
            devices_dict[device_fingerprint] = {
                "loc": device_location,
                "first": current_time,
                "recent": current_time
            }
            needs_update = True
        
        # Only update Directus if something changed
        if needs_update:
            # Encrypt the updated devices dictionary
            encrypted_devices, _ = await self.encryption_service.encrypt_with_user_key(
                json.dumps(devices_dict), vault_key_id
            )
            
            # Update the user record
            update_data = {
                "encrypted_devices": encrypted_devices
            }
            
            update_response = await self._make_api_request("PATCH", url, json=update_data)
            
            if update_response.status_code == 200:
                return True, "Device information updated successfully"
            else:
                return False, f"Failed to update device info: {update_response.status_code}"
        else:
            # No changes needed
            return True, "Device information is up to date"
            
    except Exception as e:
        error_msg = f"Error updating device info: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


async def check_user_device(self, user_id: str, device_fingerprint: str) -> bool:
    """
    Check if a device fingerprint exists in a user's known devices
    - Uses get_user_profile to retrieve cached user data including devices
    - Returns True if the device is known, False otherwise
    """
    try:
        success, profile, message = await self.get_user_profile(user_id)
        
        if success and profile and "devices" in profile:
            # Check if the fingerprint exists in the devices
            return device_fingerprint in profile["devices"]
        else:
            logger.warning(f"Failed to get user profile for device check: {message}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking user device: {str(e)}", exc_info=True)
        return False
