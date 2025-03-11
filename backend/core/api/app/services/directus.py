import os
import httpx
import logging
import asyncio
from fastapi import HTTPException, Depends
from app.services.cache import CacheService

logger = logging.getLogger(__name__)

class DirectusService:
    """
    Service for interacting with Directus CMS API
    """
    
    def __init__(self, cache_service: CacheService = None):
        """Initialize the Directus service with configuration from environment variables"""
        # Use the CMS_URL from environment, fallback to internal docker network URL
        self.base_url = os.getenv("CMS_URL", "http://cms:8055")
        self.token = os.getenv("CMS_TOKEN")
        self.admin_email = os.getenv("ADMIN_EMAIL")
        self.admin_password = os.getenv("ADMIN_PASSWORD")
        self.auth_token = None
        self.admin_token = None  # Separate token with admin privileges
        self._auth_lock = None  # Initialize as None, will create when needed
        
        # Cache settings
        self.cache = cache_service or CacheService()
        self.cache_ttl = int(os.getenv("DIRECTUS_CACHE_TTL", "3600"))  # Default 1 hour cache
        self.token_ttl = int(os.getenv("DIRECTUS_TOKEN_TTL", "43200"))  # Default 12 hours for tokens
        
        # Log information about the configuration (mask the token if available)
        if self.token:
            masked_token = self.token[:4] + "..." + self.token[-4:] if len(self.token) > 8 else "****"
            logger.info(f"DirectusService initialized with URL: {self.base_url}, Token: {masked_token}")
        else:
            logger.warning("DirectusService initialized WITHOUT a token! Will try to authenticate with admin credentials.")
    
    async def get_auth_lock(self):
        """Get the auth lock, creating it if needed"""
        if self._auth_lock is None:
            self._auth_lock = asyncio.Lock()
        return self._auth_lock
    
    async def ensure_auth_token(self, admin_required=False):
        """
        Ensure we have a valid authentication token, refreshing if necessary
        Always use admin credentials since Directus is only accessed via local network
        """
        # First check if we already have the admin token in memory
        if self.admin_token:
            return self.admin_token
            
        # If not looking for admin token but we have a regular one,
        # still return it for backwards compatibility
        if not admin_required and self.auth_token:
            return self.auth_token
            
        # If not in memory, check cache for admin token
        admin_cache_key = "directus_admin_token"
        cached_token = await self.cache.get(admin_cache_key)
        
        if cached_token:
            self.admin_token = cached_token
            logger.debug("Using cached admin token")
            return cached_token
        
        # If we get here, we need to authenticate with admin credentials
        # Use a lock to prevent multiple simultaneous login attempts
        auth_lock = await self.get_auth_lock()
        async with auth_lock:
            # Check again in case another request got the token while we were waiting
            if self.admin_token:
                return self.admin_token
                
            # Always use admin login since we're on local Docker network
            if self.admin_email and self.admin_password:
                try:
                    logger.info(f"Attempting to login to Directus as {self.admin_email}")
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
                                # Always store as admin token
                                self.admin_token = new_token
                                # Also store as auth token for backwards compatibility
                                self.auth_token = new_token
                                # Cache the admin token
                                await self.cache.set(admin_cache_key, new_token, ttl=self.token_ttl)
                                logger.info("Successfully obtained fresh ADMIN token via login")
                                return new_token
                        else:
                            logger.error(f"Admin login failed with status {response.status_code}: {response.text}")
                except Exception as e:
                    logger.error(f"Admin login failed: {str(e)}")
                    
            # If we get here, authentication failed
            logger.error("Admin authentication failed!")
            return None
    
    async def get_invite_code(self, code: str) -> dict:
        """
        Retrieve an invite code from Directus
        Returns the invite code data or None if not found
        """
        # Check cache first
        cache_key = f"invite_code:{code}"
        cached_data = await self.cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Using cached invite code data for code: {code}")
            return cached_data
            
        # Always get admin token since we need admin privileges
        token = await self.ensure_auth_token(admin_required=True)
        if not token:
            logger.error("Cannot connect to Directus: Authentication failed")
            return None
        
        try:
            logger.info(f"Checking invite code: {code}")
            headers = {"Authorization": f"Bearer {token}"}
            
            # Try both collection names since we've seen inconsistencies
            collection_names = ["invite_codes", "invitecode"]
            
            for collection_name in collection_names:
                url = f"{self.base_url}/items/{collection_name}"
                params = {"filter[code][_eq]": code}
                
                logger.debug(f"Making request to: {url} with params: {params}")
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url,
                        headers=headers,
                        params=params
                    )
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        items = response_data.get("data", [])
                        
                        if items:
                            logger.info(f"Found invite code in collection {collection_name}")
                            # Cache the result - but only if valid (remaining uses > 0)
                            if items[0].get("remaining_uses", 0) > 0:
                                await self.cache.set(cache_key, items[0], ttl=self.cache_ttl)
                            return items[0]
                    else:
                        logger.warning(f"Directus API error for {collection_name}: {response.status_code} - {response.text}")
            
            # If we tried all collections and found nothing
            logger.info(f"Invite code not found: {code}")
            return None
                
        except Exception as e:
            logger.exception(f"Error connecting to CMS: {str(e)}")
            return None

    async def test_connection(self) -> bool:
        """
        Test the connection to Directus and verify authentication
        Returns True if connection is successful, False otherwise
        """
        token = await self.ensure_auth_token()
        if not token:
            return False
        
        try:
            logger.info(f"Testing connection to Directus at {self.base_url}")
            headers = {"Authorization": f"Bearer {token}"}
            
            async with httpx.AsyncClient() as client:
                # Try server/ping which should work for any authenticated user
                response = await client.get(
                    f"{self.base_url}/server/ping",
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info("Successfully connected to Directus")
                    return True
                
                logger.error(f"Failed to connect to Directus: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.exception(f"Error testing connection to Directus: {str(e)}")
            return False
