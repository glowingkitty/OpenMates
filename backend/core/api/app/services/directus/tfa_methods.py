import httpx
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def generate_2fa_secret(self, user_token: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Generate a 2FA secret for a user using their token for authentication.
    Returns (success, response_data, message)
    """
    try:
        if not user_token:
            logger.error("No user token provided for 2FA secret generation")
            return False, None, "Authentication token required"
            
        # Use the user's token for authentication
        headers = {"Authorization": f"Bearer {user_token}"}
        
        # Make request to Directus 2FA generate endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/users/me/tfa/generate",
                headers=headers,
                json={"password": password}
            )
        
        status_code = response.status_code
        success = 200 <= status_code < 300
        
        try:
            response_data = response.json().get("data", {})
        except Exception:
            response_data = {"text": response.text}
            
        if not success:
            error_msg = f"Failed to generate 2FA secret: {status_code}: {response_data}"
            logger.error(error_msg)
            return False, None, error_msg
            
        return True, response_data, "2FA secret generated successfully"
            
    except Exception as e:
        error_msg = f"Error during 2FA secret generation: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def enable_2fa(self, user_token: str, secret: str, otp: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Enable 2FA for a user using their token for authentication.
    Returns (success, response_data, message)
    """
    try:
        if not user_token:
            logger.error("No user token provided for 2FA enablement")
            return False, None, "Authentication token required"
            
        # Use the user's token for authentication
        headers = {"Authorization": f"Bearer {user_token}"}
        
        # Make request to Directus 2FA enable endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/users/me/tfa/enable",
                headers=headers,
                json={
                    "secret": secret,
                    "otp": otp
                }
            )
        
        status_code = response.status_code
        success = 200 <= status_code < 300
        
        try:
            response_data = response.json().get("data", {})
        except Exception:
            response_data = {"text": response.text}
            
        if not success:
            error_msg = f"Failed to enable 2FA: {status_code}: {response_data}"
            logger.error(error_msg)
            return False, None, error_msg
            
        return True, response_data, "2FA enabled successfully"
            
    except Exception as e:
        error_msg = f"Error during 2FA enablement: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def verify_2fa_code(self, user_token: str, code: str) -> Tuple[bool, str]:
    """
    Verify a 2FA code using the user's token for authentication.
    Returns (success, message)
    """
    try:
        if not user_token:
            logger.error("No user token provided for 2FA verification")
            return False, "Authentication token required"
            
        # Use the user's token for authentication
        headers = {"Authorization": f"Bearer {user_token}"}
        
        # Make request to Directus 2FA verify endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/tfa",
                headers=headers,
                json={"otp": code}
            )
        
        status_code = response.status_code
        success = 200 <= status_code < 300
        
        if not success:
            error_msg = f"Failed to verify 2FA code: {status_code}"
            logger.error(error_msg)
            return False, error_msg
            
        return True, "2FA code verified successfully"
            
    except Exception as e:
        error_msg = f"Error during 2FA verification: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg