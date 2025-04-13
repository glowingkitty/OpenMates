import logging
import aiohttp
import json

logger = logging.getLogger(__name__)

async def update_user(self, user_id: str, update_data: dict) -> bool:
    """
    Update a user's data in Directus
    
    Parameters:
    - user_id: ID of the user to update
    - update_data: Dictionary of fields to update
    
    Returns:
    - bool: True if the update was successful, False otherwise
    """
    try:
        logger.debug(f"Attempting to update user {user_id} in Directus.")
        
        # Ensure we have admin token
        await self.ensure_auth_token(admin_required=True)
        if not self.admin_token:
            logger.error("Failed to get admin token for user update")
            return False
            
        # Update the user - use direct API call
        url = f"{self.base_url}/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json"
        }
        
        # Use aiohttp directly
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=update_data) as response:
                success = response.status == 200
                
                if not success:
                    error_text = await response.text()
                    logger.error(f"Failed to update user {user_id} in Directus. Status: {response.status}, Response: {error_text}")
                    return False

        # Log the successful Directus update
        logger.info(f"Successfully updated user in Directus.")
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {str(e)}")
        return False