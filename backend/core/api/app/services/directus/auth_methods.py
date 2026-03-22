import os
import httpx
import logging
import asyncio

logger = logging.getLogger(__name__)

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
    """
    Check if the token is still valid and return user data.
    
    Returns:
        Tuple[bool, Optional[Dict]]: (is_valid, user_data)
        - is_valid: True if token is valid, False otherwise
        - user_data: User data from /users/me endpoint if valid, None otherwise
    """
    if not token:
        return False, None
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/users/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code == 200:
                logger.debug("Token is valid")
                user_data = response.json().get("data", {})
                return True, user_data
            elif response.status_code == 401:
                logger.debug("Token is invalid or expired")
                return False, None
            else:
                logger.warning(f"Unexpected response checking token: {response.status_code}")
                return False, None
    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        return False, None

async def login_admin(self):
    """Get a fresh admin token by logging in"""
    if not (self.admin_email and self.admin_password):
        logger.error("Cannot login: Admin credentials not available")
        return None
        
    try:
        logger.debug(f"Logging in to Directus as {self.admin_email}")
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
                    logger.debug("Successfully obtained fresh ADMIN token via login")
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
    
    # If we have an admin token and not forcing refresh, assume it's valid
    # The API request method will handle 401s and force a refresh if needed
    if self.admin_token and not force_refresh:
        return self.admin_token
    
    admin_cache_key = "directus_admin_token"
    cached_token = await self.cache.get(admin_cache_key)
    
    if cached_token and not force_refresh:
        # Use cached token optimistically
        self.admin_token = cached_token
        logger.debug("Using cached admin token")
        return cached_token
    
    # If we reach here, we need a new token
    auth_lock = await self.get_auth_lock()
    async with auth_lock:
        # Double check if another process got the token while we were waiting
        if self.admin_token and not force_refresh:
            return self.admin_token
        
        # Login to get a fresh token
        new_token = await self.login_admin()
        if new_token:
            return new_token
        
        logger.error("Admin authentication failed!")
        return None
