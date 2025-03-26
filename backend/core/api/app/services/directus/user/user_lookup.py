import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional, Tuple


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def get_user_by_email(self, email: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Find a user by their email address
    - Converts real email to hash-based email for lookup
    - Returns (success, user_data, message)
    """
    try:
        # Hash the email for lookup using the service method
        logger.debug(f"Hashing email for lookup")
        hashed_email = await self.encryption_service.hash_email(email)

        # Create a valid email format using the hash
        directus_email = f"{hashed_email[:64]}@example.com"
        
        logger.info(f"Checking for user with hashed email (last 8 chars: {hashed_email[-8:]})")
        # Query Directus for the user
        url = f"{self.base_url}/users"
        params = {"filter": json.dumps({"email": {"_eq": directus_email}})}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            users = data.get("data", [])
            
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
        # Convert the Unix timestamp to ISO-8601 format
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
