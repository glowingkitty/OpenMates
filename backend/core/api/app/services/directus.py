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
        self.base_url = os.getenv("CMS_URL", "http://cms:8055")
        self.token = os.getenv("CMS_TOKEN")
        self.admin_email = os.getenv("ADMIN_EMAIL")
        self.admin_password = os.getenv("ADMIN_PASSWORD")
        self.auth_token = None
        self.admin_token = None
        self._auth_lock = None
        
        self.cache = cache_service or CacheService()
        self.cache_ttl = int(os.getenv("DIRECTUS_CACHE_TTL", "3600"))
        self.token_ttl = int(os.getenv("DIRECTUS_TOKEN_TTL", "43200"))
        
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
    
    async def ensure_auth_token(self, admin_required=False):
        if self.admin_token:
            return self.admin_token
            
        if not admin_required and self.auth_token:
            return self.auth_token
            
        admin_cache_key = "directus_admin_token"
        cached_token = await self.cache.get(admin_cache_key)
        
        if cached_token:
            self.admin_token = cached_token
            logger.debug("Using cached admin token")
            return cached_token
        
        auth_lock = await self.get_auth_lock()
        async with auth_lock:
            if self.admin_token:
                return self.admin_token
                
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
                                self.admin_token = new_token
                                self.auth_token = new_token
                                await self.cache.set(admin_cache_key, new_token, ttl=self.token_ttl)
                                logger.info("Successfully obtained fresh ADMIN token via login")
                                return new_token
                        else:
                            logger.error(f"Admin login failed with status {response.status_code}: {response.text}")
                except Exception as e:
                    logger.error(f"Admin login failed: {str(e)}")
                    
            logger.error("Admin authentication failed!")
            return None
    
    async def get_invite_code(self, code: str) -> dict:
        cache_key = f"invite_code:{code}"
        cached_data = await self.cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Using cached invite code data for code: {code}")
            return cached_data
            
        token = await self.ensure_auth_token(admin_required=True)
        if not token:
            logger.error("Cannot connect to Directus: Authentication failed")
            return None
        
        try:
            logger.info(f"Checking invite code: {code}")
            headers = {"Authorization": f"Bearer {token}"}
            collection_name = "invite_codes"
            url = f"{self.base_url}/items/{collection_name}"
            params = {"filter[code][_eq]": code}
            
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
        token = await self.ensure_auth_token(admin_required=True)
        if not token:
            logger.error("Cannot fetch invite codes: Authentication failed")
            return []
        
        try:
            logger.info("Fetching all invite codes from Directus")
            headers = {"Authorization": f"Bearer {token}"}
            collection_name = "invite_codes"
            url = f"{self.base_url}/items/{collection_name}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=headers
                )
                
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
