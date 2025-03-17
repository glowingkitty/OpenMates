import os
import httpx
import logging
import asyncio
import uuid
import json
from fastapi import HTTPException, Depends
from app.services.cache import CacheService
from app.utils.email_hash import hash_email
from app.utils.encryption import EncryptionService
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class DirectusService:
    """
    Service for interacting with Directus CMS API
    """
    
    def __init__(self, cache_service: CacheService = None):
        self.base_url = os.getenv("CMS_URL", "http://cms:8055")
        self.token = os.getenv("CMS_TOKEN")
        self.admin_email = os.getenv("ADMIN_EMAIL")
        self.admin_password = os.getenv("ADMIN_PASSWORD")
        self.auth_token = None
        self.admin_token = None
        self._auth_lock = None
        self.max_retries = int(os.getenv("DIRECTUS_MAX_RETRIES", "3"))
        
        self.cache = cache_service or CacheService()
        self.cache_ttl = int(os.getenv("DIRECTUS_CACHE_TTL", "3600"))
        self.token_ttl = int(os.getenv("DIRECTUS_TOKEN_TTL", "43200"))
        self.encryption_service = EncryptionService()
        
        if self.token:
            masked_token = self.token[:4] + "..." + self.token[-4:] if len(self.token) > 8 else "****"
            logger.info(f"DirectusService initialized with URL: {self.base_url}, Token: {masked_token}")
        else:
            logger.warning("DirectusService initialized WITHOUT a token! Will try to authenticate with admin credentials.")
    
    async def get_auth_lock(self):
        if self._auth_lock is None:
            self._auth_lock = asyncio.Lock()
        return self._auth_lock
    
    async def clear_tokens(self):
        self.auth_token = None
        self.admin_token = None
        admin_cache_key = "directus_admin_token"
        await self.cache.delete(admin_cache_key)
        logger.info("Cleared Directus tokens from memory and cache")
    
    async def validate_token(self, token):
        """Check if the token is still valid"""
        if not token:
            return False
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/users/me",
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if response.status_code == 200:
                    logger.debug("Token is valid")
                    return True
                elif response.status_code == 401:
                    logger.debug("Token is invalid or expired")
                    return False
                else:
                    logger.warning(f"Unexpected response checking token: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
            return False
    
    async def login_admin(self):
        """Get a fresh admin token by logging in"""
        if not (self.admin_email and self.admin_password):
            logger.error("Cannot login: Admin credentials not available")
            return None
            
        try:
            logger.info(f"Logging in to Directus as {self.admin_email}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/auth/login",
                    json={
                        "email": self.admin_email,
                        "password": self.admin_password
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if 'data' in data and 'access_token' in data['data']:
                        new_token = data['data']['access_token']
                        self.admin_token = new_token
                        self.auth_token = new_token
                        admin_cache_key = "directus_admin_token"
                        await self.cache.set(admin_cache_key, new_token, ttl=self.token_ttl)
                        logger.info("Successfully obtained fresh ADMIN token via login")
                        return new_token
                else:
                    logger.error(f"Admin login failed with status {response.status_code}: {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Admin login failed: {str(e)}")
            return None
    
    async def ensure_auth_token(self, admin_required=False, force_refresh=False):
        """Get a valid authentication token, refreshing if necessary"""
        # Always use admin token regardless of admin_required parameter
        admin_required = True
        
        # If we have an admin token and not forcing refresh, check if it's still valid
        if self.admin_token and not force_refresh:
            is_valid = await self.validate_token(self.admin_token)
            if is_valid:
                return self.admin_token
            logger.warning("Cached admin token is invalid or expired, refreshing...")
        
        admin_cache_key = "directus_admin_token"
        cached_token = await self.cache.get(admin_cache_key)
        
        if cached_token and not force_refresh:
            # Validate the cached token before using it
            is_valid = await self.validate_token(cached_token)
            if is_valid:
                self.admin_token = cached_token
                logger.debug("Using validated cached admin token")
                return cached_token
        
        # If we reach here, we need a new token
        auth_lock = await self.get_auth_lock()
        async with auth_lock:
            # Double check if another process got the token while we were waiting
            if self.admin_token and not force_refresh:
                is_valid = await self.validate_token(self.admin_token)
                if is_valid:
                    return self.admin_token
            
            # Login to get a fresh token
            new_token = await self.login_admin()
            if new_token:
                return new_token
            
            logger.error("Admin authentication failed!")
            return None
    
    async def _make_api_request(self, method, url, headers=None, **kwargs):
        """Make an API request with token refresh capability"""
        headers = headers or {}
        
        for attempt in range(self.max_retries):
            if attempt > 0:
                logger.info(f"Retry attempt {attempt} for {method} {url}")
            
            # Get a fresh token if this is a retry
            token = await self.ensure_auth_token(force_refresh=(attempt > 0))
            if not token:
                raise HTTPException(status_code=500, detail="Failed to authenticate with CMS")
            
            headers["Authorization"] = f"Bearer {token}"
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await getattr(client, method.lower())(url, headers=headers, **kwargs)
                    
                    if response.status_code == 401 and "TOKEN_EXPIRED" in response.text:
                        if attempt < self.max_retries - 1:
                            logger.warning("Token expired, will refresh and retry")
                            await self.clear_tokens()
                            continue
                    
                    return response
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Request failed: {str(e)}. Retrying...")
                    await asyncio.sleep(1)  # Add a small delay before retrying
                else:
                    raise e
        
        # This should never happen because of the exception above, but just in case
        raise HTTPException(status_code=500, detail="Maximum retry attempts reached")

    async def get_invite_code(self, code: str) -> dict:
        cache_key = f"invite_code:{code}"
        cached_data = await self.cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Using cached invite code data for code: {code}")
            return cached_data
            
        try:
            logger.info(f"Checking invite code: {code}")
            collection_name = "invite_codes"
            url = f"{self.base_url}/items/{collection_name}"
            params = {"filter[code][_eq]": code}
            
            response = await self._make_api_request(
                "GET", 
                url, 
                params=params
            )
            
            if response.status_code == 200:
                response_data = response.json()
                items = response_data.get("data", [])
                
                if items:
                    logger.info(f"Found invite code in collection {collection_name}")
                    await self.cache.set(cache_key, items[0], ttl=self.cache_ttl)
                    return items[0]
            else:
                logger.warning(f"Directus API error for {collection_name}: {response.status_code} - {response.text}")
        
            logger.info(f"Invite code not found: {code}")
            return None
                
        except Exception as e:
            logger.exception(f"Error connecting to CMS: {str(e)}")
            return None

    async def get_all_invite_codes(self):
        try:
            logger.info("Fetching all invite codes from Directus")
            collection_name = "invite_codes"
            url = f"{self.base_url}/items/{collection_name}"
            
            response = await self._make_api_request("GET", url)
            
            if response.status_code == 200:
                response_data = response.json()
                items = response_data.get("data", [])
                
                if items:
                    logger.info(f"Found {len(items)} invite codes")
                    return items
                else:
                    logger.info("No invite codes found")
                    return []
            else:
                logger.warning(f"Directus API error: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching all invite codes: {str(e)}", exc_info=True)
            return []

    async def create_user(self, username: str, email: str, password: str, 
                          is_admin: bool = False, role: str = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Create a new user in Directus
        - Creates a unique encryption key for the user in Vault
        - Stores hashed email for authentication
        - Stores encrypted email and username using the user's key
        - Returns (success, user_data, message)
        """
        try:
            # Initialize Vault and ensure transit engine exists
            await self.encryption_service.ensure_keys_exist()
            
            # Create a dedicated encryption key for this user
            vault_key_id = await self.encryption_service.create_user_key(str(uuid.uuid4()))
            
            # Hash the email for authentication
            hashed_email = hash_email(email)
            
            # Encrypt sensitive data with the user-specific key
            encrypted_email_address, key_version = await self.encryption_service.encrypt_with_user_key(email, vault_key_id)
            encrypted_username, _ = await self.encryption_service.encrypt_with_user_key(username, vault_key_id)
            encrypted_credit_balance, _ = await self.encryption_service.encrypt_with_user_key("0", vault_key_id)
            
            # Create the user payload with no cleartext sensitive data
            user_data = {
                "email": hashed_email,  # Using hashed email as username for login
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
                
                # Non-sensitive data
                "is_admin": is_admin
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
    
    async def login_user(self, email: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Authenticate a user with Directus
        - Uses hashed email for authentication
        - Returns (success, auth_data, message)
        """
        try:
            # Hash the email for login
            hashed_email = hash_email(email)
            
            # Prepare login payload
            login_data = {
                "email": hashed_email,  # Use hashed email for authentication
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
                
                # Extract cookies for setting in our response
                cookies = response.cookies
                
                # Return success with auth data and cookies
                return True, {
                    "user": auth_data.get("user"),
                    "cookies": {c.name: c.value for c in cookies}
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
            # Prepare logout payload
            logout_data = {}
            if refresh_token:
                logout_data["refresh_token"] = refresh_token
            
            # Make request to Directus logout endpoint
            response = requests.post(
                f"{self.base_url}/auth/logout",
                json=logout_data
            )
            
            if response.status_code == 200:
                return True, "Logout successful"
            else:
                error_msg = f"Logout failed: {response.text}"
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
            # Make request to Directus logout-all endpoint
            response = requests.post(
                f"{self.base_url}/auth/logout/all",
                headers=self._get_admin_headers()
            )
            
            if response.status_code == 200:
                return True, "All sessions logged out"
            else:
                error_msg = f"Logout all failed: {response.text}"
                logger.warning(error_msg)
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Error during logout all: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    async def get_user_by_email(self, email: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Find a user by their email address
        - Uses hashed email for lookup
        - Returns (success, user_data, message)
        """
        try:
            # Hash the email for lookup
            hashed_email = hash_email(email)
            
            # Query Directus for the user using async httpx
            url = f"{self.base_url}/users"
            params = {"filter": json.dumps({"email": {"_eq": hashed_email}})}
            
            response = await self._make_api_request("GET", url, params=params)
            
            if response.status_code == 200:
                users = response.json().get("data", [])
                if users and len(users) > 0:
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
        try:
            # Make request to Directus refresh endpoint
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/auth/refresh",
                    json={"refresh_token": refresh_token},
                    headers={"Content-Type": "application/json"}
                )
            
            if response.status_code == 200:
                auth_data = response.json().get("data", {})
                
                # If we have user data, get the user info
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
                
                # Extract cookies for setting in our response
                cookies = response.cookies
                
                # Return success with auth data and cookies
                return True, {
                    "user": auth_data.get("user"),
                    "cookies": {c.name: c.value for c in cookies}
                }, "Token refreshed successfully"
            else:
                error_msg = f"Token refresh failed: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return False, None, error_msg
                
        except Exception as e:
            error_msg = f"Error during token refresh: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, None, error_msg
