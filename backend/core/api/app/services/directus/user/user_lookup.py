import logging
import json
import base64
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List # Add List import


logger = logging.getLogger(__name__)

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


async def get_user_by_hashed_email(self, hashed_email: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Find a user by their hashed email address.
    Returns (success, user_data, message)
    """
    try:
        # Query Directus for a user with the matching hashed_email
        url = f"{self.base_url}/users"
        params = {"filter": json.dumps({"hashed_email": {"_eq": hashed_email}})}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            users = data.get("data", [])
            
            if users and len(users) > 0:
                logger.info(f"Found user with matching hashed email")
                user = users[0]
                return True, user, "User found"
            else:
                logger.info(f"No user found with matching hashed email")
                return False, None, "User not found"
        else:
            error_msg = f"Failed to query user by hashed email: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error querying user by hashed email: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def authenticate_user_by_lookup_hash(self, hashed_email: str, lookup_hash: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user by first finding them with hashed_email and then checking if the lookup_hash is in their lookup_hashes array.
    This is more efficient than separate calls as it combines the lookup and verification in one operation.
    
    Returns (success, user_data, message)
    """
    try:
        # Query Directus for a user with the matching hashed_email
        url = f"{self.base_url}/users"
        params = {"filter": json.dumps({"hashed_email": {"_eq": hashed_email}})}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            users = data.get("data", [])
            
            if not users or len(users) == 0:
                logger.info(f"No user found with matching hashed email")
                return False, None, "Invalid credentials"
                
            user = users[0]
            user_id = user.get("id")
            lookup_hashes = user.get("lookup_hashes", [])
            
            # Check if the provided lookup_hash is in the user's lookup_hashes array
            if lookup_hash in lookup_hashes:
                logger.info(f"Lookup hash verified for user {user_id}")
                return True, user, "Authentication successful"
            else:
                logger.warning(f"Invalid lookup hash for user {user_id}")
                return False, None, "Invalid credentials"
        else:
            error_msg = f"Failed to query user by hashed email: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error authenticating user: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg

async def verify_user_lookup_hash(self, user_id: str, lookup_hash: str) -> Tuple[bool, str]:
    """
    Verify if the provided lookup_hash is in the user's lookup_hashes array.
    Returns (success, message)
    """
    try:
        # Get the user's lookup_hashes
        url = f"{self.base_url}/users/{user_id}"
        params = {"fields": ["lookup_hashes"]}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            user_data = response.json().get("data", {})
            lookup_hashes = user_data.get("lookup_hashes", [])
            
            if lookup_hash in lookup_hashes:
                return True, "Lookup hash verified"
            else:
                return False, "Invalid lookup hash"
        else:
            error_msg = f"Failed to get user lookup hashes: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error verifying user lookup hash: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

async def add_user_lookup_hash(self, user_id: str, lookup_hash: str) -> Tuple[bool, str]:
    """
    Add a lookup hash to the user's lookup_hashes array.
    Returns (success, message)
    """
    try:
        # First get the current lookup_hashes
        url = f"{self.base_url}/users/{user_id}"
        params = {"fields": ["lookup_hashes"]}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code != 200:
            error_msg = f"Failed to get user lookup hashes: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
        user_data = response.json().get("data", {})
        lookup_hashes = user_data.get("lookup_hashes", [])
        
        # Check if the hash already exists
        if lookup_hash in lookup_hashes:
            return True, "Lookup hash already exists"
            
        # Add the new hash
        lookup_hashes.append(lookup_hash)
        
        # Update the user
        update_url = f"{self.base_url}/users/{user_id}"
        update_data = {"lookup_hashes": lookup_hashes}
        
        update_response = await self._make_api_request("PATCH", update_url, json=update_data)
        
        if update_response.status_code == 200:
            return True, "Lookup hash added successfully"
        else:
            error_msg = f"Failed to update user lookup hashes: {update_response.status_code} - {update_response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error adding user lookup hash: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

async def get_user_fields_direct(self, user_id: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    """
    Fetches specific fields for a user directly from Directus, bypassing cache.

    Args:
        user_id: The ID of the user to fetch.
        fields: A list of field names to retrieve (e.g., ["encrypted_credit_balance", "vault_key_id"]).

    Returns:
        A dictionary containing the requested fields and their values,
        or None if the user is not found or an error occurs.
        Returns field value as None if the field itself doesn't exist for the user.
    """
    if not user_id or not fields:
        logger.warning("get_user_fields_direct called with invalid user_id or empty fields list.")
        return None

    try:
        # Ensure 'id' is always included if not present, as it's often useful context
        if 'id' not in fields:
            fields_to_fetch = ['id'] + fields
        else:
            fields_to_fetch = fields
            
        fields_query = ",".join(fields_to_fetch)
        logger.info(f"Fetching direct fields '{fields_query}' for user {user_id}")
        url = f"{self.base_url}/users/{user_id}?fields={fields_query}"
        response = await self._make_api_request("GET", url)

        if response.status_code == 404:
            logger.warning(f"User {user_id} not found when fetching direct fields.")
            return None
        elif response.status_code != 200:
            logger.error(f"Failed to retrieve direct fields for user {user_id}: {response.status_code} - {response.text}")
            return None

        user_data = response.json().get("data", {})
        
        # Ensure all originally requested fields are in the result dict, even if null
        # Exclude the 'id' we might have added internally unless it was originally requested
        result_data = {field: user_data.get(field) for field in fields}
        
        logger.info(f"Successfully fetched direct fields for user {user_id}.")
        return result_data

    except Exception as e:
        logger.error(f"Error in get_user_fields_direct for user {user_id}: {str(e)}", exc_info=True)
        return None
