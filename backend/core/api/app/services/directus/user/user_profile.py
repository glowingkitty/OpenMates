import logging
import json
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

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
        
        if not vault_key_id:
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
            
            # Keep sensitive data encrypted (don't decrypt these)
            "encrypted_email_address": user_data.get("encrypted_email_address"),
            "encrypted_settings": user_data.get("encrypted_settings"),
        }
        
        # Decrypt fields that are safe to cache and commonly needed
        try:
            # Decrypt username
            if "encrypted_username" in user_data:
                decrypted_username = await self.encryption_service.decrypt_with_user_key(
                    user_data["encrypted_username"], vault_key_id
                )
                profile["username"] = decrypted_username
            
            # Decrypt credit balance
            if "encrypted_credit_balance" in user_data:
                decrypted_credits = await self.encryption_service.decrypt_with_user_key(
                    user_data["encrypted_credit_balance"], vault_key_id
                )
                try:
                    profile["credits"] = int(decrypted_credits)
                except ValueError:
                    try:
                        profile["credits"] = int(float(decrypted_credits))
                    except ValueError:
                        logger.error(f"Invalid credit balance format: {decrypted_credits}")
                        profile["credits"] = 0
            
            # Decrypt profile image URL if present
            if "encrypted_profileimage_url" in user_data and user_data["encrypted_profileimage_url"]:
                decrypted_image_url = await self.encryption_service.decrypt_with_user_key(
                    user_data["encrypted_profileimage_url"], vault_key_id
                )
                profile["profile_image_url"] = decrypted_image_url
            
            # Decrypt and parse devices if present
            if "encrypted_devices" in user_data and user_data["encrypted_devices"]:
                decrypted_devices = await self.encryption_service.decrypt_with_user_key(
                    user_data["encrypted_devices"], vault_key_id
                )
                devices_dict = json.loads(decrypted_devices) if decrypted_devices else {}
                profile["devices"] = devices_dict
            else:
                profile["devices"] = {}
                
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
