import logging
import json
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def get_user_profile(self, user_id: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Get a complete user profile with all decrypted fields in a single request
    - Makes a single API call to get user data
    - Decrypts appropriate fields (username, credits, profile image, etc.)
    - Keeps sensitive data encrypted (email, settings)
    - Caches the result for future use
    - Returns (success, user_profile, message)
    """
    try:
        # Check cache first
        cache_key = f"user_profile:{user_id}"
        cached_profile = await self.cache.get(cache_key)
        
        if cached_profile:
            logger.info(f"Using cached user profile for user {user_id}")
            return True, cached_profile, "Profile retrieved from cache"
        
        # Not in cache, fetch from Directus
        logger.info(f"Fetching user profile for user {user_id} from Directus")
        url = f"{self.base_url}/users/{user_id}"
        response = await self._make_api_request("GET", url)
        
        if response.status_code != 200:
            error_msg = f"Failed to retrieve user: {response.status_code}"
            logger.warning(error_msg)
            return False, None, error_msg
            
        user_data = response.json().get("data", {})
        
        vault_key_id = user_data.get("vault_key_id")
        logger.info(f"Found vault_key_id")
        
        if not vault_key_id:
            logger.error("No vault_key_id found in user data")
            return False, None, "User has no encryption key"
        
        # Create a profile object with both encrypted and decrypted data
        profile = {
            "id": user_id,
            "is_admin": user_data.get("is_admin", False),
            "last_opened": user_data.get("last_opened"),
            "status": user_data.get("status"),
            "role": user_data.get("role"),
            "last_access": user_data.get("last_access"),
            "vault_key_id": vault_key_id,
            "vault_key_version": user_data.get("vault_key_version"),
            "tfa_last_used": user_data.get("tfa_last_used"),  # Include 2FA last used timestamp
            
            # Keep sensitive data encrypted (don't decrypt these)
            "encrypted_email_address": user_data.get("encrypted_email_address"),
            "encrypted_tfa_secret": user_data.get("encrypted_tfa_secret"), # Fetch the encrypted secret
            "encrypted_settings": user_data.get("encrypted_settings"),
        }

        # Decrypt fields that are safe to cache and commonly needed (DO NOT decrypt tfa_secret here)
        try:
            # Add debug logs for each decryption attempt
            for field, encrypted_field in [
                ("username", "encrypted_username"),
                ("credits", "encrypted_credit_balance"),
                ("profile_image_url", "encrypted_profileimage_url"),
                ("devices", "encrypted_devices"),
                ("tfa_app_name", "encrypted_tfa_app_name")
            ]:
                if encrypted_field in user_data and user_data[encrypted_field]:
                    try:
                        decrypted_value = await self.encryption_service.decrypt_with_user_key(
                            user_data[encrypted_field], vault_key_id
                        )
                        
                        if decrypted_value:
                            if field == "devices":
                                profile[field] = json.loads(decrypted_value)
                            elif field == "credits":
                                profile[field] = int(float(decrypted_value))
                            else:
                                profile[field] = decrypted_value
                    except Exception as e:
                        logger.error(f"[Debug] Error decrypting {field}: {str(e)}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error decrypting user data: {str(e)}")
            # Continue with whatever we have successfully decrypted
        
        # Cache the profile
        await self.cache.set(cache_key, profile, ttl=self.cache_ttl)
        
        return True, profile, "User profile retrieved successfully"
            
    except Exception as e:
        error_msg = f"Error getting user profile: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def get_user_profile_by_token(self, access_token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Get user profile using an access token
    """
    try:
        logger.info("[Debug] Getting user profile with access token")
        
        # Make request to Directus /users/me endpoint
        url = f"{self.base_url}/users/me"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
        if response.status_code != 200:
            logger.error(f"[Debug] Failed to get user profile: {response.status_code}")
            return False, None, "Failed to get user profile"
            
        user_data = response.json().get("data", {})
        logger.info("[Debug] Got raw user data from Directus")
        
        # Get the user's vault key ID for decryption
        vault_key_id = user_data.get("vault_key_id")
        if not vault_key_id:
            logger.error("[Debug] No vault key ID found")
            return False, None, "No encryption key found"
            
        # Decrypt necessary fields
        try:
            if "encrypted_username" in user_data:
                username = await self.encryption_service.decrypt_with_user_key(
                    user_data["encrypted_username"],
                    vault_key_id
                )
                user_data["username"] = username
                logger.info(f"[Debug] Decrypted username: {bool(username)}")
        except Exception as e:
            logger.error(f"[Debug] Error decrypting fields: {e}")
            
        return True, user_data, "Profile retrieved successfully"
            
    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}")
        return False, None, str(e)
