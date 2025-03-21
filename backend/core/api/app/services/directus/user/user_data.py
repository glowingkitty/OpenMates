import logging

logger = logging.getLogger(__name__)

async def get_user_credits(self, user_id: str) -> int:
    """
    Get a user's credit balance
    - Uses get_user_profile to retrieve cached user data including credits
    - Returns the credit balance as an integer
    """
    try:
        success, profile, message = await self.get_user_profile(user_id)
        
        if success and profile:
            return profile.get("credits", 0)
        else:
            logger.warning(f"Failed to get user profile for credits: {message}")
            return 0
            
    except Exception as e:
        logger.error(f"Error getting user credits: {str(e)}", exc_info=True)
        return 0

async def get_user_username(self, user_id: str) -> str:
    """
    Get a user's username
    - Uses get_user_profile to retrieve cached user data including username
    """
    try:
        success, profile, message = await self.get_user_profile(user_id)
        
        if success and profile:
            return profile.get("username", "")
        else:
            logger.warning(f"Failed to get user profile for username: {message}")
            return ""
            
    except Exception as e:
        logger.error(f"Error getting username: {str(e)}", exc_info=True)
        return ""

async def get_user_profile_image(self, user_id: str) -> str:
    """
    Get a user's profile image URL
    - Uses get_user_profile to retrieve cached user data including profile image URL
    """
    try:
        success, profile, message = await self.get_user_profile(user_id)
        
        if success and profile:
            return profile.get("profile_image_url", "")
        else:
            logger.warning(f"Failed to get user profile for profile image: {message}")
            return ""
            
    except Exception as e:
        logger.error(f"Error getting profile image: {str(e)}", exc_info=True)
        return ""

async def invalidate_user_profile_cache(self, user_id: str) -> bool:
    """
    Invalidate the cached user profile when user data is updated
    """
    try:
        cache_key = f"user_profile:{user_id}"
        await self.cache.delete(cache_key)
        logger.info(f"Invalidated profile cache for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error invalidating user profile cache: {str(e)}")
        return False
