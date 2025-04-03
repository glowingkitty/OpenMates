import logging
import json
from typing import Dict, Any, Optional, Tuple, List # Added List import

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
        # Fetch encrypted_gifted_credits_for_signup as well
        url = f"{self.base_url}/users/{user_id}?fields=*,encrypted_gifted_credits_for_signup" 
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
            
        # Determine TFA status based on raw data BEFORE creating cached profile
        # Check if the secret field exists and is not null/empty
        tfa_enabled_status = bool(user_data.get("encrypted_tfa_secret"))
        logger.info(f"Determined tfa_enabled status for user {user_id}: {tfa_enabled_status}")
        
        # Create a profile object with both encrypted and decrypted data
        profile = {
            "id": user_id,
            "tfa_enabled": tfa_enabled_status, # Add the determined status here
            "is_admin": user_data.get("is_admin", False),
            "last_opened": user_data.get("last_opened"),
            "status": user_data.get("status"),
            "role": user_data.get("role"),
            "last_access": user_data.get("last_access"),
            "vault_key_id": vault_key_id,
            "vault_key_version": user_data.get("vault_key_version"),
            "language": user_data.get("language", "en"),
            "darkmode": user_data.get("darkmode", False),
            "tfa_last_used": user_data.get("tfa_last_used"),  # Include 2FA last used timestamp
            "consent_privacy_and_apps_default_settings": user_data.get("consent_privacy_and_apps_default_settings"),
            "consent_mates_default_settings": user_data.get("consent_mates_default_settings"),
            
            # Keep sensitive data encrypted (don't decrypt these)
            "encrypted_email_address": user_data.get("encrypted_email_address"),
            "encrypted_settings": user_data.get("encrypted_settings"),
        }

        # Decrypt fields that are safe to cache and commonly needed (DO NOT decrypt tfa_secret here)
        try:
            # Add debug logs for each decryption attempt
            # Add gifted_credits_for_signup to the list of fields to decrypt
            for field, encrypted_field in [
                ("username", "encrypted_username"),
                ("credits", "encrypted_credit_balance"),
                ("profile_image_url", "encrypted_profileimage_url"),
                ("devices", "encrypted_devices"),
                ("tfa_app_name", "encrypted_tfa_app_name"),
                ("gifted_credits_for_signup", "encrypted_gifted_credits_for_signup") # Added gift decryption
            ]:
                # Check if the encrypted field exists in the raw data fetched from Directus
                if encrypted_field in user_data and user_data[encrypted_field]:
                    try:
                        decrypted_value = await self.encryption_service.decrypt_with_user_key(
                            user_data[encrypted_field], vault_key_id
                        )
                        
                        # Correctly indented block starts here
                        if decrypted_value:
                            if field == "devices":
                                profile[field] = json.loads(decrypted_value)
                            # Handle credits and gifted credits as integers
                            elif field == "credits" or field == "gifted_credits_for_signup": 
                                try:
                                    profile[field] = int(float(decrypted_value))
                                except (ValueError, TypeError):
                                    logger.error(f"Could not convert decrypted {field} '{decrypted_value}' to int for user {user_id}")
                                    profile[field] = 0 # Default to 0 if conversion fails
                            else:
                                profile[field] = decrypted_value
                            # No need to remove encrypted field here, as it wasn't added to profile dict initially
                    except Exception as e:
                        logger.error(f"[Debug] Error decrypting {field}: {str(e)}", exc_info=True)
                        # No need to remove encrypted field here
                
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

# --- New functions to fetch sensitive TFA data directly ---

async def get_decrypted_tfa_secret(self, user_id: str) -> Optional[str]:
    """
    Fetches ONLY the encrypted TFA secret for a user directly from Directus,
    decrypts it, and returns the plain secret. Bypasses cache entirely.
    Returns None if secret not found, not enabled, or decryption fails.
    """
    try:
        logger.info(f"Fetching encrypted TFA secret directly for user {user_id}")
        # Explicitly import httpx here if not already available globally in the file context
        # import httpx # Assuming httpx is available or imported elsewhere
        url = f"{self.base_url}/users/{user_id}?fields=encrypted_tfa_secret,vault_key_id"
        # Use the service's internal method for making requests
        response = await self._make_api_request("GET", url) 

        if response.status_code != 200:
            logger.warning(f"Failed to retrieve user TFA data: {response.status_code} for user {user_id}")
            return None

        user_data = response.json().get("data", {})
        encrypted_secret = user_data.get("encrypted_tfa_secret")
        vault_key_id = user_data.get("vault_key_id")

        if not encrypted_secret:
            logger.info(f"No encrypted_tfa_secret found for user {user_id} (likely not enabled).")
            return None
        if not vault_key_id:
            logger.error(f"No vault_key_id found for user {user_id} when fetching TFA secret.")
            return None

        # Decrypt the secret using the service's encryption instance
        decrypted_secret = await self.encryption_service.decrypt_with_user_key(
            encrypted_secret, vault_key_id
        )

        if not decrypted_secret:
            logger.error(f"Failed to decrypt TFA secret for user {user_id}.")
            return None

        logger.info(f"Successfully fetched and decrypted TFA secret for user {user_id}")
        return decrypted_secret

    except Exception as e:
        logger.error(f"Error getting/decrypting TFA secret for user {user_id}: {str(e)}", exc_info=True)
        return None

async def get_tfa_backup_code_hashes(self, user_id: str) -> Optional[List[str]]:
    """
    Fetches ONLY the TFA backup code hashes for a user directly from Directus.
    Bypasses cache entirely. Parses the JSON string into a list.
    Returns None if field not found or error occurs. Returns empty list if field is empty/null.
    """
    try:
        logger.info(f"Fetching TFA backup code hashes directly for user {user_id}")
        # Explicitly import json here if not already available globally
        # import json # Assuming json is available or imported elsewhere
        url = f"{self.base_url}/users/{user_id}?fields=tfa_backup_codes_hashes"
        # Use the service's internal method for making requests
        response = await self._make_api_request("GET", url)

        if response.status_code != 200:
            logger.warning(f"Failed to retrieve user backup code hashes: {response.status_code} for user {user_id}")
            return None

        user_data = response.json().get("data", {})
        hashed_codes_raw = user_data.get("tfa_backup_codes_hashes")

        if hashed_codes_raw is None:
            logger.info(f"No tfa_backup_codes_hashes field found or field is null for user {user_id}.")
            return [] # Return empty list if field is null/missing

        hashed_codes = []
        if isinstance(hashed_codes_raw, str):
            if not hashed_codes_raw.strip(): # Handle empty string case
                 logger.info(f"tfa_backup_codes_hashes field is an empty string for user {user_id}.")
                 return []
            try:
                hashed_codes = json.loads(hashed_codes_raw)
                if not isinstance(hashed_codes, list):
                    logger.warning(f"Parsed tfa_backup_codes_hashes for user {user_id} is not a list, treating as empty.")
                    hashed_codes = []
            except json.JSONDecodeError:
                logger.error(f"Failed to parse tfa_backup_codes_hashes JSON string for user {user_id}: '{hashed_codes_raw}'")
                return None # Indicate parsing error
        elif isinstance(hashed_codes_raw, list):
             # Should not happen based on schema, but handle defensively
            hashed_codes = hashed_codes_raw
        else:
            logger.warning(f"Unexpected type for tfa_backup_codes_hashes for user {user_id}: {type(hashed_codes_raw)}")
            return None # Indicate unexpected data type

        logger.info(f"Successfully fetched {len(hashed_codes)} TFA backup code hashes for user {user_id}")
        return hashed_codes

    except Exception as e:
        logger.error(f"Error getting TFA backup code hashes for user {user_id}: {str(e)}", exc_info=True)
        return None


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
