import logging
import aiohttp

logger = logging.getLogger(__name__)

async def delete_user(self, user_id: str) -> bool:
    """Delete a user from Directus"""
    try:
        # First invalidate any cached data
        await self.invalidate_user_profile_cache(user_id)
        
        # Ensure we have admin token - check auth_methods.py to see that admin_required is the parameter name
        await self.ensure_auth_token(admin_required=True)  # Changed from admin=True
        if not self.admin_token:
            logger.error("Failed to get admin token for user deletion")
            return False
            
        # Delete the user - use direct API call
        url = f"{self.base_url}/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json"
        }
        
        # Use aiohttp directly
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                success = response.status == 204
                
                if not success:
                    error_text = await response.text()
                    logger.error(f"Failed to delete user {user_id}. Status: {response.status}, Response: {error_text}")
                    return False
                    
        # Also clear any related cache entries
        cache_key = f"user:{user_id}"
        await self.cache.delete(cache_key)
        
        # Delete profile image cache
        profile_image_key = f"user_profile_image:{user_id}"
        await self.cache.delete(profile_image_key)
        
        # Log the deletion
        logger.info(f"User deleted: {user_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {str(e)}")
        return False
