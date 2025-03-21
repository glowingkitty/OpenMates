import httpx
import logging
import asyncio
import hashlib
import json
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

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
        
        # Create a valid email format using the hash
        directus_email = f"{hashed_email[:64]}@example.com"
        
        # Prepare login payload with the hash-based email
        login_data = {
            "email": directus_email,
            "password": password,
            "mode": "cookie"
        }
        
        # Make request to Directus auth endpoint
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
    Log out all sessions for a user
    - Returns (success, message)
    """
    try:
        # Get token first
        token = await self.ensure_auth_token(admin_required=True)
        if not token:
            return False, "Failed to get admin token"
        
        # Make request to Directus logout-all endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/logout/all",
                headers={"Authorization": f"Bearer {token}"},
                json={"user": user_id}
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

async def refresh_token(self, refresh_token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Refresh an authentication token using the refresh token
    Returns (success, auth_data, message)
    """
    # Use faster retry logic with fixed delay
    max_retries = 2
    fixed_delay = 0.2
    
    for attempt in range(max_retries + 1):
        try:
            # Add debug logging for the refresh token
            masked_token = refresh_token[:5] + "..." + refresh_token[-5:] if len(refresh_token) > 10 else "***"
            logger.info(f"Attempting to refresh token with: {masked_token}" + (f" (attempt {attempt+1}/{max_retries+1})" if attempt > 0 else ""))
            
            # Check if we have cached user data for this token to use as fallback
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            cache_key = f"session:{token_hash}"
            cached_session = await self.cache.get(cache_key) or None
            
            # Make request to Directus refresh endpoint
            async with httpx.AsyncClient(timeout=2.0) as client:
                cookies = {"directus_refresh_token": refresh_token}
                
                response = await client.post(
                    f"{self.base_url}/auth/refresh",
                    json={"refresh_token": refresh_token, "mode": "cookie"},
                    cookies=cookies,
                    headers={"Content-Type": "application/json"}
                )
            
                if response.status_code == 200:
                    auth_data = response.json().get("data", {})
                    
                    if "access_token" in auth_data:
                        # Get user data using the new access token
                        user_response = await client.get(
                            f"{self.base_url}/users/me",
                            headers={"Authorization": f"Bearer {auth_data['access_token']}"}
                        )
                        
                        if user_response.status_code == 200:
                            user_data = user_response.json().get("data", {})
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
                            
                            # Cache user data for fallback
                            if cached_session:
                                cached_session["user_id"] = user_data.get("id")
                                cached_session["username"] = user_data.get("username")
                                await self.cache.set(cache_key, cached_session, ttl=3600)
                
                    # Extract cookies for setting in our response
                    cookies_dict = dict(response.cookies)
                    
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
                        return True, {
                            "user": {
                                "id": cached_session.get("user_id"),
                                "username": cached_session.get("username"),
                                "is_admin": cached_session.get("is_admin", False)
                            },
                            "cookies": {}
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
                            "cookies": {}
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
