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
        # First invalidate any cached data
        await self.invalidate_user_profile_cache(user_id)
        
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
                    logger.error(f"Failed to update user {user_id}. Status: {response.status}, Response: {error_text}")
                    return False
                    
        # Also clear any related cache entries
        cache_key = f"user:{user_id}"
        await self.cache.delete(cache_key)
        
        # Delete profile image cache if updating profile image
        if "encrypted_profileimage_url" in update_data:
            profile_image_key = f"user_profile_image:{user_id}"
            await self.cache.delete(profile_image_key)
        
        # Log the update
        logger.info(f"User updated: {user_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {str(e)}")
        return False