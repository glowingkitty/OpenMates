import os
import httpx
import logging
import asyncio
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class DirectusService:
    """
    Service for interacting with Directus CMS API
    """
    
    def __init__(self):
        """Initialize the Directus service with configuration from environment variables"""
        # Use the CMS_URL from environment, fallback to internal docker network URL
        self.base_url = os.getenv("CMS_URL", "http://cms:8055")
        self.token = os.getenv("CMS_TOKEN")
        self.admin_email = os.getenv("ADMIN_EMAIL")
        self.admin_password = os.getenv("ADMIN_PASSWORD")
        self.auth_token = None
        self.admin_token = None  # Separate token with admin privileges
        self._auth_lock = None  # Initialize as None, will create when needed
        
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
        If admin_required is True, will specifically get an admin token
        """
        # If admin required, check if we have admin token
        if admin_required and self.admin_token:
            return self.admin_token
            
        # If not admin required and we have regular token
        if not admin_required and self.auth_token:
            return self.auth_token
            
        # Use a lock to prevent multiple simultaneous login attempts
        auth_lock = await self.get_auth_lock()
        async with auth_lock:
            # Check again in case another request got the token while we were waiting
            if admin_required and self.admin_token:
                return self.admin_token
            if not admin_required and self.auth_token:
                return self.auth_token
                
            # Try with environment token first if not specifically looking for admin token
            if not admin_required and self.token:
                # Test if token works
                headers = {"Authorization": f"Bearer {self.token}"}
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            f"{self.base_url}/server/ping",
                            headers=headers
                        )
                        if response.status_code == 200:
                            self.auth_token = self.token
                            logger.info("Using token from environment variables")
                            return self.auth_token
                except Exception as e:
                    logger.warning(f"Environment token failed: {str(e)}, will try admin login")

            # Always try admin login if we need admin privileges or if regular token failed
            if self.admin_email and self.admin_password:
                try:
                    logger.info(f"Attempting to login to Directus as {self.admin_email} (admin_required={admin_required})")
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
                                # Store token in appropriate place based on request type
                                if admin_required:
                                    self.admin_token = new_token
                                    logger.info("Successfully obtained fresh ADMIN token via login")
                                else:
                                    self.auth_token = new_token
                                    logger.info("Successfully obtained fresh token via admin login")
                                return new_token
                        else:
                            logger.error(f"Admin login failed with status {response.status_code}: {response.text}")
                except Exception as e:
                    logger.error(f"Admin login failed: {str(e)}")
                    
            # If we get here, all authentication methods failed
            logger.error(f"All authentication methods failed! admin_required={admin_required}")
            return None
    
    async def get_invite_code(self, code: str) -> dict:
        """
        Retrieve an invite code from Directus
        Returns the invite code data or None if not found
        """
        # Get an auth token - first try normal token, then admin if needed
        token = await self.ensure_auth_token(admin_required=False)
        if not token:
            logger.error("Cannot connect to Directus: Authentication failed")
            return None
        
        try:
            logger.info(f"Checking invite code: {code}")
            headers = {"Authorization": f"Bearer {token}"}
            
            # Try both collection names since we've seen inconsistencies
            collection_names = ["invite_codes", "invitecode"]
            data = None
            
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
                    
                    if response.status_code == 401:
                        logger.warning(f"Regular token unauthorized for {collection_name}, trying admin credentials")
                        # Try with admin credentials
                        admin_token = await self.ensure_auth_token(admin_required=True)
                        if not admin_token:
                            logger.error("Failed to get admin token")
                            continue
                        
                        # Try the request again with admin token
                        headers = {"Authorization": f"Bearer {admin_token}"}
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
