import logging
import json
import uuid
import time
import os
import random
import string
from typing import Dict, Any, Optional, Tuple


logger = logging.getLogger(__name__)

def _generate_account_id() -> str:
    """
    Generate a random 6-character account ID using A-Z and 0-9.
    
    Returns:
        str: A 6-character account ID
    """
    charset = string.ascii_uppercase + string.digits
    return ''.join(random.choices(charset, k=7))

async def _generate_unique_account_id(self, max_attempts: int = 10) -> Optional[str]:
    """
    Generate a unique account ID by checking against existing ones in the database.
    
    Args:
        max_attempts: Maximum number of generation attempts before giving up
        
    Returns:
        str: A unique account ID, or None if unable to generate after max_attempts
    """
    for attempt in range(max_attempts):
        account_id = _generate_account_id()
        
        # Check if this account ID already exists
        try:
            params = {
                "filter[account_id][_eq]": account_id,
                "limit": 1
            }
            existing_users = await self.get_items("directus_users", params)
            
            if not existing_users:
                # Account ID is unique
                logger.info(f"Generated unique account ID on attempt {attempt + 1}")
                return account_id
            else:
                logger.debug(f"Account ID {account_id} already exists, trying again (attempt {attempt + 1})")
                
        except Exception as e:
            logger.error(f"Error checking account ID uniqueness: {e}")
            # Continue trying with a new ID
            continue
    
    logger.error(f"Failed to generate unique account ID after {max_attempts} attempts")
    return None

async def create_user(self,
                      username: str,
                      email: str,
                      lookup_hash: str,
                      hashed_email: str,
                      is_admin: bool = False, role: str = None,
                      device_fingerprint: str = None,
                      device_location: str = None,
                      language: str = "en",
                      darkmode: bool = False,
                      ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
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
        vault_key_id = await self.encryption_service.create_user_key()

        # Generate a unique account ID for this user
        account_id = await _generate_unique_account_id(self)
        if not account_id:
            error_msg = "Failed to generate unique account ID"
            logger.error(error_msg)
            return False, None, error_msg

        # Use client-provided hashed_email (required parameter)
        # Create a valid email format using the hash (max 64 chars for username part)
        directus_email = f"{hashed_email[:64]}@example.com"
        # Create a password for Directus by hashing the directus_email
        directus_password = await self.encryption_service.hash_email(directus_email)
        
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
            "password": directus_password,  # Add the hashed directus_email as password
            "status": "active",
            "role": role,
            "vault_key_id": vault_key_id,
            "vault_key_version": key_version,
            "encrypted_email_address": encrypted_email_address,
            "encrypted_username": encrypted_username,
            "encrypted_credit_balance": encrypted_credit_balance,
            "encrypted_devices": encrypted_devices,
            "is_admin": is_admin,
            "last_opened": "/signup/one_time_codes",
            "language": language,
            "darkmode": darkmode,
            "hashed_email": hashed_email,  # Store the client-provided hashed email
            "lookup_hashes": [lookup_hash],  # Store the client-provided lookup hash in an array
            "account_id": account_id  # Store the generated account ID
        }

        # Make request to Directus
        url = f"{self.base_url}/users"
        response = await self._make_api_request("POST", url, json=user_data)
        
        if response.status_code == 200:
            created_user = response.json().get("data")
            
            # Update the require_invite_code cache if needed
            signup_limit = int(os.getenv("SIGNUP_LIMIT", "0"))
            if signup_limit > 0:
                try:
                    # Get the total user count after creating this user
                    total_users = await self.get_total_users_count()
                    require_invite_code = total_users >= signup_limit
                    
                    # Update the cache with the new value
                    from backend.core.api.app.services.cache import CacheService
                    cache_service = CacheService()
                    await cache_service.set("require_invite_code", require_invite_code, ttl=172800)  # Cache for 48 hours
                    
                    logger.info(f"Updated require_invite_code cache after user creation: limit={signup_limit}, users={total_users}, required={require_invite_code}")
                except Exception as e:
                    logger.error(f"Error updating require_invite_code cache after user creation: {e}")
            
            return True, created_user, "User created successfully"
        else:
            error_msg = f"Failed to create user: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error creating user: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg
