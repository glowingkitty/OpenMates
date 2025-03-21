import httpx
import logging
import asyncio
import hashlib
import json
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def login_user(self, email: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user with Directus
    - Converts real email to hash-based email for lookup
    - Gets access token from login
    - Uses access token to fetch user data
    - Returns (success, auth_data, message)
    """
    try:
        # Hash the email for login
        from app.utils.email_hash import hash_email
        hashed_email = hash_email(email)
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
                            
                    # Add more decryption here as needed
                    
                except Exception as e:
                    logger.error(f"Error decrypting user data: {str(e)}")
            
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
    Only refreshes the token with Directus - does not fetch user data
    Returns (success, {"cookies": {...}}, message)
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
                # Only return the new cookies - no user data needed
                return True, {
                    "cookies": dict(response.cookies)
                }, "Token refreshed"
                
            logger.error(f"Token refresh failed: {response.status_code}")
            return False, None, "Token refresh failed"
            
    except Exception as e:
        logger.error(f"Error during token refresh: {str(e)}")
        return False, None, str(e)
