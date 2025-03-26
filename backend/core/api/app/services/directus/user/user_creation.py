import logging
import json
import uuid
import time
from typing import Dict, Any, Optional, Tuple


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def create_user(self, username: str, email: str, password: str, 
                      is_admin: bool = False, role: str = None,
                      device_fingerprint: str = None,
                      device_location: str = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Create a new user in Directus
    - Creates a unique encryption key for the user in Vault
    - Stores email as a hash with @example.com to pass validation
    - Stores encrypted email and username using the user's key
    - Returns (success, user_data, message)
    """
    try:
        # Initialize Vault and ensure transit engine exists
        await self.encryption_service.ensure_keys_exist()
        
        # Create a dedicated encryption key for this user
        vault_key_id = await self.encryption_service.create_user_key(str(uuid.uuid4()))

        # Hash the email for authentication using the service method
        hashed_email = await self.encryption_service.hash_email(email)

        # Create a valid email format using the hash (max 64 chars for username part)
        directus_email = f"{hashed_email[:64]}@example.com"
        
        # Encrypt sensitive data with the user-specific key
        encrypted_email_address, key_version = await self.encryption_service.encrypt_with_user_key(email, vault_key_id)
        encrypted_username, _ = await self.encryption_service.encrypt_with_user_key(username, vault_key_id)
        encrypted_credit_balance, _ = await self.encryption_service.encrypt_with_user_key("0", vault_key_id)
        
        # If device fingerprint provided, create and encrypt devices dictionary
        encrypted_devices = None
        if device_fingerprint and device_location:
            current_time = int(time.time())
            devices_dict = {
                device_fingerprint: {
                    "loc": device_location,
                    "first": current_time,
                    "recent": current_time
                }
            }
            encrypted_devices, _ = await self.encryption_service.encrypt_with_user_key(
                json.dumps(devices_dict), vault_key_id
            )
        
        # Create the user payload with no cleartext sensitive data
        user_data = {
            "email": directus_email,
            "password": password,
            "status": "active",
            "role": role,
            "vault_key_id": vault_key_id,
            "vault_key_version": key_version,
            "encrypted_email_address": encrypted_email_address,
            "encrypted_username": encrypted_username,
            "encrypted_credit_balance": encrypted_credit_balance,
            "encrypted_devices": encrypted_devices,
            "is_admin": is_admin,
            "last_opened": "/signup/step-3"
        }
        
        # Make request to Directus
        url = f"{self.base_url}/users"
        response = await self._make_api_request("POST", url, json=user_data)
        
        if response.status_code == 200:
            created_user = response.json().get("data")
            return True, created_user, "User created successfully"
        else:
            error_msg = f"Failed to create user: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error creating user: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg
