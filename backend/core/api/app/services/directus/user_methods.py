import httpx
import logging
import time
import json
import uuid
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

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
        
        # Hash the email for authentication
        from app.utils.email_hash import hash_email
        hashed_email = hash_email(email)
        
        # Create a valid email format using the hash (max 64 chars for username part)
        directus_email = f"{hashed_email[:64]}@example.com"
        
        # Encrypt sensitive data with the user-specific key
        encrypted_email_address, key_version = await self.encryption_service.encrypt_with_user_key(email, vault_key_id)
        encrypted_username, _ = await self.encryption_service.encrypt_with_user_key(username, vault_key_id)
        encrypted_credit_balance, _ = await self.encryption_service.encrypt_with_user_key("0", vault_key_id)
        
        # If device fingerprint provided, create and encrypt devices dictionary
        encrypted_devices = None
        if device_fingerprint and device_location:
            import time
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
            "email": directus_email,  # Use hash-based email that passes validation
            "password": password,
            "status": "active",  # Automatically activate since email is verified
            "role": role,  # Role ID from Directus
            
            # Store the user's Vault key ID and version
            "vault_key_id": vault_key_id,
            "vault_key_version": key_version,  # Single version field for all encrypted data
            
            # Store encrypted sensitive data
            "encrypted_email_address": encrypted_email_address,
            "encrypted_username": encrypted_username,
            "encrypted_credit_balance": encrypted_credit_balance,
            
            # Add encrypted devices if available
            "encrypted_devices": encrypted_devices,
            
            # Non-sensitive data
            "is_admin": is_admin,
            
            # Add last_opened field to track the signup step
            "last_opened": "/signup/step-3"
        }
        
        # Make request to Directus using async httpx
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
                "loc": device_location,  # Store the location for new device
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

async def update_user_devices(self, user_id: str, encrypted_devices: str) -> Tuple[bool, str]:
    """
    Update a user's encrypted devices directly
    """
    try:
        # Update the user record with new encrypted devices
        url = f"{self.base_url}/users/{user_id}"
        update_data = {"encrypted_devices": encrypted_devices}
        
        response = await self._make_api_request("PATCH", url, json=update_data)
        
        if response.status_code == 200:
            return True, "Devices updated successfully"
        else:
            return False, f"Failed to update devices: {response.status_code}"
            
    except Exception as e:
        error_msg = f"Error updating devices: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

async def login_user(self, email: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user with Directus
    - Converts real email to hash-based email for lookup
    - Returns (success, auth_data, message)
    """
    try:
        # Hash the email for login
        from app.utils.email_hash import hash_email
        hashed_email = hash_email(email)
        
        # Create a valid email format using the hash (same format as in create_user)
        directus_email = f"{hashed_email[:64]}@example.com"
        
        # Prepare login payload with the hash-based email
        login_data = {
            "email": directus_email,
            "password": password,
            "mode": "cookie"  # This will set HTTP-only cookies
        }
        
        # Make request to Directus auth endpoint using async httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/login",
                json=login_data
            )
        
        if response.status_code == 200:
            auth_data = response.json().get("data", {})
            
            # If we have user data, decrypt encrypted fields
            if "user" in auth_data:
                user_data = auth_data["user"]
                
                # Get the user's vault key ID
                vault_key_id = user_data.get("vault_key_id")
                
                # Try to decrypt the username for display
                if vault_key_id and "encrypted_username" in user_data:
                    try:
                        decrypted_username = await self.encryption_service.decrypt_with_user_key(
                            user_data["encrypted_username"], 
                            vault_key_id
                        )
                        if decrypted_username:
                            user_data["username"] = decrypted_username
                    except Exception as e:
                        logger.error(f"Error decrypting username: {str(e)}")
            
            # Extract cookies safely
            cookies_dict = {}
            try:
                for name, value in response.cookies.items():
                    cookies_dict[name] = value
            except Exception as e:
                logger.error(f"Error processing cookies: {str(e)}")
                
            # Return success with auth data and cookies
            return True, {
                "user": auth_data.get("user"),
                "cookies": cookies_dict
            }, "Login successful"
        else:
            error_msg = f"Login failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error during login: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def logout_user(self, refresh_token: str = None) -> Tuple[bool, str]:
    """
    Log out a user from Directus
    - Returns (success, message)
    """
    try:
        if not refresh_token:
            logger.warning("No refresh token provided for logout")
            return False, "No refresh token provided"
            
        # Prepare logout payload
        logout_data = {"refresh_token": refresh_token}
        
        # Make request to Directus logout endpoint using async httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/logout",
                json=logout_data
            )
        
        if response.status_code == 200:
            logger.info("Logout successful on Directus")
            return True, "Logout successful"
        else:
            error_msg = f"Logout failed: {response.status_code}: {response.text}"
            logger.warning(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error during logout: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

async def logout_all_sessions(self, user_id: str) -> Tuple[bool, str]:
    """
    Log out all sessions for a user
    - Returns (success, message)
    """
    try:
        # Get token first
        token = await self.ensure_auth_token(admin_required=True)
        if not token:
            return False, "Failed to get admin token"
        
        # Make request to Directus logout-all endpoint using async httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/logout/all",
                headers={"Authorization": f"Bearer {token}"},
                json={"user": user_id}  # Add user parameter to specify which user
            )
        
        if response.status_code == 200:
            logger.info(f"All sessions logged out for user {user_id}")
            return True, "All sessions logged out"
        else:
            error_msg = f"Logout all failed: {response.status_code}: {response.text}"
            logger.warning(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error during logout all: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

async def get_user_by_email(self, email: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Find a user by their email address
    - Converts real email to hash-based email for lookup
    - Returns (success, user_data, message)
    """
    try:
        # Hash the email for lookup
        from app.utils.email_hash import hash_email
        logger.debug(f"Hashing email for lookup")
        hashed_email = hash_email(email)
        
        # Create a valid email format using the hash (same format as in create_user)
        directus_email = f"{hashed_email[:64]}@example.com"
        
        logger.info(f"Checking for user with hashed email (last 8 chars: {hashed_email[-8:]})")
        # Query Directus for the user using async httpx
        url = f"{self.base_url}/users"
        params = {"filter": json.dumps({"email": {"_eq": directus_email}})}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            users = data.get("data", [])
            
            # Debug log to help investigate issues
            logger.debug(f"User lookup returned {len(users)} results")
            
            if users and len(users) > 0:
                logger.info(f"Found user with matching hashed email")
                user = users[0]
                
                # Get the user's vault key ID
                vault_key_id = user.get("vault_key_id")
                
                # Try to decrypt encrypted fields if present
                if vault_key_id and "encrypted_username" in user:
                    try:
                        decrypted_username = await self.encryption_service.decrypt_with_user_key(
                            user["encrypted_username"], 
                            vault_key_id
                        )
                        if decrypted_username:
                            user["username"] = decrypted_username
                    except Exception as e:
                        logger.error(f"Error decrypting username: {str(e)}")
                
                return True, user, "User found"
            else:
                logger.info(f"No user found with matching hashed email")
                return False, None, "User not found"
        else:
            error_msg = f"Failed to get user: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error getting user by email: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def refresh_token(self, refresh_token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Refresh an authentication token using the refresh token
    Returns (success, auth_data, message)
    """
    # Use faster retry logic with fixed delay
    max_retries = 2  # Try up to 3 times total (initial + 2 retries)
    fixed_delay = 0.2  # 200ms delay between retries
    
    for attempt in range(max_retries + 1):  # +1 for the initial attempt
        try:
            # Add debug logging for the refresh token
            masked_token = refresh_token[:5] + "..." + refresh_token[-5:] if len(refresh_token) > 10 else "***"
            logger.info(f"Attempting to refresh token with: {masked_token}" + (f" (attempt {attempt+1}/{max_retries+1})" if attempt > 0 else ""))
            
            # Check if we have cached user data for this token to use as fallback
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            cache_key = f"session:{token_hash}"
            cached_session = await self.cache.get(cache_key) or None  # Initialize with None if not found
            
            # Make request to Directus refresh endpoint
            # Set both cookies AND json payload for maximum compatibility
            async with httpx.AsyncClient(timeout=2.0) as client:
                # Create cookies dict with the refresh token
                cookies = {"directus_refresh_token": refresh_token}
                
                # Make the request with both cookies and JSON payload
                response = await client.post(
                    f"{self.base_url}/auth/refresh",
                    json={"refresh_token": refresh_token, "mode": "cookie"},
                    cookies=cookies,
                    headers={"Content-Type": "application/json"}
                )
            
                if response.status_code == 200:
                    auth_data = response.json().get("data", {})
                    
                    # If we have user data, get the user info - this must be done while the client is still open
                    if "access_token" in auth_data:
                        # Get user data using the new access token
                        user_response = await client.get(
                            f"{self.base_url}/users/me",
                            headers={"Authorization": f"Bearer {auth_data['access_token']}"}
                        )
                        
                        if user_response.status_code == 200:
                            user_data = user_response.json().get("data", {})
                            
                            # Get the user's vault key ID
                            vault_key_id = user_data.get("vault_key_id")
                            
                            # Try to decrypt the username for display
                            if vault_key_id and "encrypted_username" in user_data:
                                try:
                                    decrypted_username = await self.encryption_service.decrypt_with_user_key(
                                        user_data["encrypted_username"], 
                                        vault_key_id
                                    )
                                    if decrypted_username:
                                        user_data["username"] = decrypted_username
                                except Exception as e:
                                    logger.error(f"Error decrypting username: {str(e)}")
                            
                            # Add user data to auth response
                            auth_data["user"] = user_data
                            
                            # Cache user data for fallback in case of future failures
                            if cached_session:
                                cached_session["user_id"] = user_data.get("id")
                                cached_session["username"] = user_data.get("username")
                                await self.cache.set(cache_key, cached_session, ttl=3600)  # Update cache
                
                    # Extract cookies for setting in our response - httpx cookies are a dictionary-like object
                    cookies_dict = dict(response.cookies)
                    
                    # Return success with auth data and cookies
                    return True, {
                        "user": auth_data.get("user"),
                        "cookies": cookies_dict
                    }, "Token refreshed successfully"
                
                elif response.status_code in [503, 429]:  # Service unavailable or rate limited
                    if attempt < max_retries:
                        logger.warning(f"Directus service issue ({response.status_code}), retrying in {fixed_delay}s (attempt {attempt+1}/{max_retries+1})")
                        await asyncio.sleep(fixed_delay)
                        continue
                    
                    # If we have cached user data, use it as a fallback on the last attempt
                    if cached_session:
                        logger.info("Using cached user data as fallback after service unavailable")
                        # We can't refresh the token, but we can return the user data to avoid logout
                        return True, {
                            "user": {
                                "id": cached_session.get("user_id"),
                                "username": cached_session.get("username"),
                                "is_admin": cached_session.get("is_admin", False)
                            },
                            "cookies": {}  # No new cookies to set
                        }, "Using cached user data due to service unavailability"
                    
                    error_msg = f"Token refresh failed: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return False, None, error_msg
                
                else:
                    error_msg = f"Token refresh failed: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    
                    # If we have cached user data, try to use it as a fallback
                    if cached_session:
                        logger.info("Using cached user data as fallback after refresh failure")
                        return True, {
                            "user": {
                                "id": cached_session.get("user_id"),
                                "username": cached_session.get("username"),
                                "is_admin": cached_session.get("is_admin", False)
                            },
                            "cookies": {}  # No new cookies to set
                        }, "Using cached user data due to refresh failure"
                        
                    return False, None, error_msg
        
        except Exception as e:
            error_msg = f"Error during token refresh: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            if attempt < max_retries:
                logger.warning(f"Token refresh error, retrying in {fixed_delay}s (attempt {attempt+1}/{max_retries+1})")
                await asyncio.sleep(fixed_delay)
            else:
                # Check for cached user data on last attempt
                if cached_session:
                    logger.info("Using cached user data as fallback after exception")
                    return True, {
                        "user": {
                            "id": cached_session.get("user_id"),
                            "username": cached_session.get("username"),
                            "is_admin": cached_session.get("is_admin", False)
                        },
                        "cookies": {}
                    }, "Using cached user data due to errors"
                
                return False, None, error_msg
    
    # If we've exhausted all retries
    return False, None, "Maximum retry attempts reached for token refresh"

async def get_total_users_count(self) -> int:
    """
    Get the total count of registered users
    Returns the count as an integer
    """
    try:
        url = f"{self.base_url}/users"
        params = {
            "limit": 1,
            "meta": "filter_count"
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            meta = data.get("meta", {})
            filter_count = meta.get("filter_count")
            logger.debug(f"Total users count: {filter_count}")
            
            if filter_count is not None:
                return int(filter_count)
            else:
                logger.error("Filter count not returned by Directus API")
                return 0
        else:
            error_msg = f"Failed to get user count: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return 0
            
    except Exception as e:
        error_msg = f"Error getting user count: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return 0

async def get_active_users_since(self, timestamp: int) -> int:
    """
    Get the count of users who have logged in since the given timestamp
    Returns the count as an integer
    
    Args:
        timestamp: Unix timestamp to check users against
    """
    try:
        # Convert the Unix timestamp to ISO-8601 format string which is compatible with Directus
        iso_date = datetime.fromtimestamp(timestamp).isoformat()
        
        url = f"{self.base_url}/users"
        params = {
            "limit": 1,
            "meta": "filter_count",
            "filter": json.dumps({
                "last_access": {
                    "_gte": iso_date
                }
            })
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            meta = data.get("meta", {})
            filter_count = meta.get("filter_count")
            
            if filter_count is not None:
                return int(filter_count)
            else:
                logger.error("Filter count not returned by Directus API")
                return 0
        else:
            error_msg = f"Failed to get active users: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return 0
            
    except Exception as e:
        logger.error(f"Error getting active users: {str(e)}")
        return 0

async def check_user_device(self, user_id: str, device_fingerprint: str) -> bool:
    """
    Check if a device fingerprint exists in a user's known devices
    - Returns True if the device is known, False otherwise
    """
    try:
        # Get the user first to retrieve encrypted_devices and vault key
        url = f"{self.base_url}/users/{user_id}"
        response = await self._make_api_request("GET", url)
        
        if response.status_code != 200:
            logger.warning(f"Failed to retrieve user: {response.status_code}")
            return False
            
        user_data = response.json().get("data", {})
        vault_key_id = user_data.get("vault_key_id")
        encrypted_devices_str = user_data.get("encrypted_devices")
        
        # If no vault key or encrypted devices, device is unknown
        if not vault_key_id or not encrypted_devices_str:
            return False
        
        # Decrypt the devices data
        try:
            decrypted_devices = await self.encryption_service.decrypt_with_user_key(
                encrypted_devices_str, vault_key_id
            )
            devices_dict = json.loads(decrypted_devices)
            
            # Check if the fingerprint exists in the devices
            return device_fingerprint in devices_dict
            
        except Exception as e:
            logger.error(f"Error decrypting devices: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking user device: {str(e)}", exc_info=True)
        return False

async def get_user_credits(self, user_id: str) -> int:
    """
    Get a user's credit balance
    - Decrypts the encrypted_credit_balance field
    - Returns the credit balance as an integer
    """
    try:
        # Get the user data
        url = f"{self.base_url}/users/{user_id}"
        response = await self._make_api_request("GET", url)
        
        if response.status_code != 200:
            logger.warning(f"Failed to retrieve user: {response.status_code}")
            return 0
            
        user_data = response.json().get("data", {})
        vault_key_id = user_data.get("vault_key_id")
        encrypted_credit_balance = user_data.get("encrypted_credit_balance")
        
        # If no vault key or encrypted balance, return 0
        if not vault_key_id or not encrypted_credit_balance:
            return 0
        
        # Decrypt the credit balance
        try:
            decrypted_credits = await self.encryption_service.decrypt_with_user_key(
                encrypted_credit_balance, vault_key_id
            )
            
            # Convert to integer
            try:
                return int(decrypted_credits)
            except ValueError:
                # If it can't be converted to int, try float and then convert to int
                try:
                    return int(float(decrypted_credits))
                except ValueError:
                    logger.error(f"Invalid credit balance format: {decrypted_credits}")
                    return 0
                
        except Exception as e:
            logger.error(f"Error decrypting credit balance: {str(e)}")
            return 0
            
    except Exception as e:
        logger.error(f"Error getting user credits: {str(e)}", exc_info=True)
        return 0
