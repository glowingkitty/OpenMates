import httpx
import logging
from typing import Dict, Any, Optional, Tuple
import json

logger = logging.getLogger(__name__)

async def login_user(self, email: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user with Directus
    - Converts real email to hash-based email for lookup
    - Gets access token from login
    - Uses access token to fetch user data
    - Returns (success, auth_data, message)
    """
    try:
        # Hash the email for login using the service method
        hashed_email = await self.encryption_service.hash_email(email)
        directus_email = f"{hashed_email[:64]}@example.com"

        # Step 1: Get access token via login
        async with httpx.AsyncClient() as client:
            login_response = await client.post(
                f"{self.base_url}/auth/login",
                json={
                    "email": directus_email,
                    "password": password,
                    "mode": "cookie"
                }
            )
        
        if login_response.status_code != 200:
            if login_response.status_code == 401:
                logger.info("Login failed. Credentials wrong.")
            else:
                logger.error(f"Login failed: {login_response.status_code} - {login_response.text}")
            return False, None, "Login failed. Credentials wrong."
            
        login_data = login_response.json().get("data", {})
        access_token = login_data.get("access_token")
        
        if not access_token:
            logger.error("No access token received from login")
            return False, None, "No access token received"

        logger.info("Got access token from login")

        # Step 2: Use access token to get user data
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                f"{self.base_url}/users/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if user_response.status_code != 200:
                logger.error(f"Failed to get user data: {user_response.status_code}")
                return False, None, "Failed to get user data"
                
            user_data = user_response.json().get("data", {})
            
            # Step 3: Decrypt user data if needed
            vault_key_id = user_data.get("vault_key_id")
            if vault_key_id:
                try:
                    # Decrypt username if present
                    if "encrypted_username" in user_data:
                        decrypted_username = await self.encryption_service.decrypt_with_user_key(
                            user_data["encrypted_username"], vault_key_id
                        )
                        if decrypted_username:
                            user_data["username"] = decrypted_username
                        else:
                            # Log error, but don't set default. Let it propagate.
                            logger.error("Username decryption failed!")
                            # If username was present but failed decryption, remove it to avoid confusion?
                            # Or leave it as is (encrypted)? Let's leave it for now.

                    # Decrypt profile image URL if present
                    encrypted_profile_url = user_data.get("encrypted_profileimage_url")
                    if encrypted_profile_url:
                        decrypted_profile_url = await self.encryption_service.decrypt_with_user_key(
                            encrypted_profile_url, vault_key_id
                        )
                        if decrypted_profile_url:
                            user_data["profile_image_url"] = decrypted_profile_url
                        else:
                            logger.warning("Profile image URL decryption returned None. Setting to None.")
                            user_data["profile_image_url"] = None # Explicitly set to None on failure/empty
                    else:
                         # If no encrypted URL, ensure profile_image_url is None
                         user_data["profile_image_url"] = None

                    # Decrypt credit balance if present
                    encrypted_credits = user_data.get("encrypted_credit_balance")
                    if encrypted_credits:
                        decrypted_credits_str = await self.encryption_service.decrypt_with_user_key(
                            encrypted_credits, vault_key_id
                        )
                        if decrypted_credits_str:
                            try:
                                user_data["credits"] = int(float(decrypted_credits_str))
                            except ValueError:
                                # Log error, but don't set default. Let it propagate.
                                logger.error(f"Failed to convert decrypted credits '{decrypted_credits_str}' to int!")
                                # If credits were present but failed conversion, remove? Or leave encrypted? Leave for now.
                        else:
                            # Log error, but don't set default. Let it propagate.
                            logger.error("Credit balance decryption failed!")
                            # If credits were present but failed decryption, remove? Or leave encrypted? Leave for now.

                    # Decrypt tfa app name
                    encrypted_tfa_app_name = user_data.get("encrypted_tfa_app_name")
                    if encrypted_tfa_app_name:
                        decrypted_tfa_app_name = await self.encryption_service.decrypt_with_user_key(
                            encrypted_tfa_app_name, vault_key_id
                        )
                        if decrypted_tfa_app_name:
                            user_data["tfa_app_name"] = decrypted_tfa_app_name
                        else:
                            # Log error, but don't set default. Let it propagate.
                            logger.error("2FA app name decryption failed!")
                            # If tfa_app_name was present but failed decryption, remove? Or leave encrypted? Leave for now.

                    # Decrypt devices
                    encrypted_devices = user_data.get("encrypted_devices")
                    if encrypted_devices:
                        decrypted_devices = await self.encryption_service.decrypt_with_user_key(
                            encrypted_devices, vault_key_id
                        )
                        if decrypted_devices:
                            try:
                                user_data["devices"] = json.loads(decrypted_devices)
                            except json.JSONDecodeError:
                                # Log error, but don't set default. Let it propagate.
                                logger.error(f"Failed to decode decrypted devices JSON: {str(e)}")
                                # If devices were present but failed decryption, remove? Or leave encrypted? Leave for now.
                        else:
                            logger.error("Devices decryption failed!")

                    # Decrypt invoice counter
                    encrypted_invoice_counter = user_data.get("encrypted_invoice_counter")
                    if encrypted_invoice_counter:
                        decrypted_invoice_counter = await self.encryption_service.decrypt_with_user_key(
                            encrypted_invoice_counter, vault_key_id
                        )
                        if decrypted_invoice_counter:
                            try:
                                user_data["invoice_counter"] = int(decrypted_invoice_counter)
                            except ValueError:
                                # Log error, but don't set default. Let it propagate.
                                logger.error(f"Failed to convert decrypted invoice counter '{decrypted_invoice_counter}' to int!")
                                # If invoice counter was present but failed conversion, remove? Or leave encrypted? Leave for now.
                        else:
                            logger.error("Invoice counter decryption failed!")
                            # If invoice counter was present but failed decryption, remove? Or leave encrypted? Leave for now.

                except Exception as e:
                    # Log the overarching error, but avoid setting defaults here.
                    logger.error(f"Error during user data decryption block: {str(e)}")
                    # Ensure profile_image_url is None if the block failed before setting it
                    if "profile_image_url" not in user_data:
                         user_data["profile_image_url"] = None
            
            # Extract cookies for session management
            cookies_dict = {}
            try:
                for name, value in login_response.cookies.items():
                    cookies_dict[name] = value
            except Exception as e:
                logger.error(f"Error processing cookies: {str(e)}")
            
            return True, {
                "access_token": access_token,
                "user": user_data,
                "cookies": cookies_dict
            }, "Login successful"
            
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
        
        # Make request to Directus logout endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/logout",
                json=logout_data
            )
        
        if response.status_code == 204:
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
    Log out all sessions for a user by deleting all sessions from directus_sessions collection.
    
    Directus doesn't have a native /auth/logout/all endpoint, so we need to:
    1. Query all sessions for the user from directus_sessions collection
    2. Delete all those sessions using bulk delete
    
    - Returns (success, message)
    """
    try:
        # Ensure we have admin token for accessing directus_sessions collection
        token = await self.ensure_auth_token(admin_required=True)
        if not token:
            return False, "Failed to get admin token"
        
        logger.info(f"Logging out all sessions for user {user_id}")
        
        # Query all sessions for this user from directus_sessions collection
        # The 'user' field in directus_sessions references the user ID (relation to directus_users)
        session_params = {
            "filter[user][_eq]": user_id,
            "fields": "id",
            "limit": -1  # Get all sessions
        }
        
        sessions = await self.get_items("directus_sessions", params=session_params)
        
        if not sessions:
            logger.info(f"No active sessions found for user {user_id}")
            return True, "No active sessions to logout"
        
        # Extract session IDs
        session_ids = [session.get("id") for session in sessions if session.get("id")]
        
        if not session_ids:
            logger.warning(f"Found {len(sessions)} sessions but none had valid IDs for user {user_id}")
            return False, "Failed to extract session IDs"
        
        logger.info(f"Found {len(session_ids)} active sessions to delete for user {user_id}")
        
        # Delete all sessions using bulk delete
        success = await self.bulk_delete_items("directus_sessions", session_ids)
        
        if success:
            logger.info(f"Successfully logged out all {len(session_ids)} sessions for user {user_id}")
            return True, f"All {len(session_ids)} sessions logged out"
        else:
            error_msg = f"Failed to delete sessions for user {user_id}"
            logger.warning(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error during logout all: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

async def refresh_token(self, refresh_token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Refreshes the token with Directus and returns both cookies and response data.
    Returns (success, {"cookies": {...}, "data": {...}}, message)
    The response data may contain access_token in the JSON body.
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                f"{self.base_url}/auth/refresh",
                json={"refresh_token": refresh_token, "mode": "cookie"},
                cookies={"directus_refresh_token": refresh_token}
            )
            
            if response.status_code == 200:
                logger.info("Token refresh successful")
                # Parse JSON response body (may contain access_token)
                response_data = {}
                try:
                    json_data = response.json()
                    if "data" in json_data:
                        response_data = json_data["data"]
                    else:
                        response_data = json_data
                except Exception as e:
                    logger.debug(f"Could not parse JSON response body: {e}")
                
                # Return both cookies and response data
                return True, {
                    "cookies": dict(response.cookies),
                    "data": response_data
                }, "Token refreshed"
                
            logger.error(f"Token refresh failed: {response.status_code}")
            return False, None, "Token refresh failed"
            
    except Exception as e:
        logger.error(f"Error during token refresh: {str(e)}")
        return False, None, str(e)

async def login_user_with_lookup_hash(self, hashed_email: str, lookup_hash: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user with Directus using hashed_email and lookup_hash
    - First verifies the lookup_hash is valid for the user with the given hashed_email
    - Then logs in the user using the directus_email and a hash of that email as password
    - Returns (success, auth_data, message)
    """
    try:
        # First, verify the lookup_hash is valid for the user
        url = f"{self.base_url}/users"
        params = {"filter": json.dumps({"hashed_email": {"_eq": hashed_email}})}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code != 200:
            error_msg = f"Failed to query user by hashed email: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
        data = response.json()
        users = data.get("data", [])
        
        if not users or len(users) == 0:
            logger.info(f"No user found with matching hashed email")
            return False, None, "login.email_or_password_wrong.text"
            
        user = users[0]

        user_id = user.get("id")
        lookup_hashes = user.get("lookup_hashes", [])
        
        # Check if the provided lookup_hash is in the user's lookup_hashes array
        if lookup_hash not in lookup_hashes:
            logger.warning(f"Invalid lookup hash for user {user_id}")
            return False, None, "login.email_or_password_wrong.text"
            
        logger.info(f"Lookup hash verified for user {user_id}")
        
        # Now log in the user using directus_email and a hash of that email as password
        # Construct the Directus email format from hashed_email
        directus_email = f"{hashed_email[:64]}@example.com"
        # Use a hash of the directus_email as the password for Directus authentication
        directus_password = await self.encryption_service.hash_email(directus_email)
        
        async with httpx.AsyncClient() as client:
            session_response = await client.post(
                f"{self.base_url}/auth/login",
                json={
                    "email": directus_email,
                    "password": directus_password,
                    "mode": "cookie"
                }
            )
            
            if session_response.status_code != 200:
                logger.error(f"Failed to create session for user {user_id}: {session_response.status_code} - {session_response.text}")
                return False, None, "Failed to create session"
                
            session_data = session_response.json().get("data", {})
            access_token = session_data.get("access_token")
            
            if not access_token:
                logger.error("No access token received from session creation")
                return False, None, "No access token received"
                
            logger.info(f"Created session for user {user_id}")
            
            # Step 2: Use access token to get full user data (like in login_user)
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    f"{self.base_url}/users/me",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if user_response.status_code != 200:
                    logger.error(f"Failed to get user data: {user_response.status_code}")
                    return False, None, "Failed to get user data"
                    
                user_data = user_response.json().get("data", {})
                
                # Step 3: Decrypt user data if needed (like in login_user)
                # IMPORTANT: Preserve encrypted_email_address for caching and later use
                vault_key_id = user_data.get("vault_key_id")
                if vault_key_id:
                    try:
                        # Decrypt username if present
                        if "encrypted_username" in user_data:
                            decrypted_username = await self.encryption_service.decrypt_with_user_key(
                                user_data["encrypted_username"], vault_key_id
                            )
                            if decrypted_username:
                                user_data["username"] = decrypted_username
                            else:
                                logger.error("Username decryption failed!")

                        # Decrypt profile image URL if present
                        encrypted_profile_url = user_data.get("encrypted_profileimage_url")
                        if encrypted_profile_url:
                            decrypted_profile_url = await self.encryption_service.decrypt_with_user_key(
                                encrypted_profile_url, vault_key_id
                            )
                            if decrypted_profile_url:
                                user_data["profile_image_url"] = decrypted_profile_url
                            else:
                                logger.warning("Profile image URL decryption returned None. Setting to None.")
                                user_data["profile_image_url"] = None
                        else:
                            user_data["profile_image_url"] = None

                        # Decrypt credit balance if present
                        encrypted_credits = user_data.get("encrypted_credit_balance")
                        if encrypted_credits:
                            decrypted_credits_str = await self.encryption_service.decrypt_with_user_key(
                                encrypted_credits, vault_key_id
                            )
                            if decrypted_credits_str:
                                try:
                                    user_data["credits"] = int(float(decrypted_credits_str))
                                except ValueError:
                                    logger.error(f"Failed to convert decrypted credits '{decrypted_credits_str}' to int!")
                            else:
                                logger.error("Credit balance decryption failed!")

                        # Decrypt tfa app name
                        encrypted_tfa_app_name = user_data.get("encrypted_tfa_app_name")
                        if encrypted_tfa_app_name:
                            decrypted_tfa_app_name = await self.encryption_service.decrypt_with_user_key(
                                encrypted_tfa_app_name, vault_key_id
                            )
                            if decrypted_tfa_app_name:
                                user_data["tfa_app_name"] = decrypted_tfa_app_name
                            else:
                                logger.error("2FA app name decryption failed!")

                        # Decrypt devices
                        encrypted_devices = user_data.get("encrypted_devices")
                        if encrypted_devices:
                            decrypted_devices = await self.encryption_service.decrypt_with_user_key(
                                encrypted_devices, vault_key_id
                            )
                            if decrypted_devices:
                                try:
                                    user_data["devices"] = json.loads(decrypted_devices)
                                except json.JSONDecodeError:
                                    logger.error(f"Failed to decode decrypted devices JSON: {str(e)}")
                            else:
                                logger.error("Devices decryption failed!")

                        # Decrypt invoice counter
                        encrypted_invoice_counter = user_data.get("encrypted_invoice_counter")
                        if encrypted_invoice_counter:
                            decrypted_invoice_counter = await self.encryption_service.decrypt_with_user_key(
                                encrypted_invoice_counter, vault_key_id
                            )
                            if decrypted_invoice_counter:
                                try:
                                    user_data["invoice_counter"] = int(decrypted_invoice_counter)
                                except ValueError:
                                    logger.error(f"Failed to convert decrypted invoice counter '{decrypted_invoice_counter}' to int!")
                            else:
                                logger.error("Invoice counter decryption failed!")

                    except Exception as e:
                        logger.error(f"Error during user data decryption block: {str(e)}")
                        if "profile_image_url" not in user_data:
                            user_data["profile_image_url"] = None
            
            # Extract cookies for session management
            cookies_dict = {}
            try:
                for name, value in session_response.cookies.items():
                    cookies_dict[name] = value
            except Exception as e:
                logger.error(f"Error processing cookies: {str(e)}")
                
            # Return the user data and cookies (use decrypted user_data instead of original user)
            return True, {
                "access_token": access_token,
                "user": user_data,
                "cookies": cookies_dict
            }, "Authentication successful"
            
    except Exception as e:
        error_msg = f"Error during login with lookup hash: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg
