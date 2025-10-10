import logging

logger = logging.getLogger(__name__)

async def update_user(self, user_id: str, update_data: dict) -> bool:
    """
    Update a user's data in Directus using the centralized _make_api_request method.
    Updates the cache first to avoid unnecessary database reads.
    
    Parameters:
    - user_id: ID of the user to update
    - update_data: Dictionary of fields to update
    
    Returns:
    - bool: True if the update was successful, False otherwise
    """
    logger.debug(f"Attempting to update user {user_id} in Directus.")

    # Step 1: Update the cached user profile first (if it exists)
    # This avoids an unnecessary database read on the next get_user_profile() call
    cache_key = f"user_profile:{user_id}"
    try:
        cached_profile = await self.cache.get(cache_key)
        if cached_profile:
            # Update the cached profile with new data
            cached_profile.update(update_data)
            # Re-cache the updated profile
            await self.cache.set(cache_key, cached_profile, ttl=21600)  # 6 hours TTL
            logger.debug(f"Updated cached user profile for user {user_id}")
        else:
            logger.debug(f"No cached profile found for user {user_id}, will be fetched on next read")
    except Exception as cache_error:
        logger.warning(f"Failed to update cached profile for user {user_id}: {cache_error}")
        # Continue with Directus update even if cache update fails
    
    # Step 2: Update Directus database
    url = f"{self.base_url}/users/{user_id}"
    
    # _make_api_request returns the response object on success, or None on failure.
    response_obj = await self._make_api_request(
        "PATCH",
        url,
        json=update_data
    )

    if response_obj is not None and 200 <= response_obj.status_code < 300:
        logger.info(f"Successfully updated user {user_id} in Directus.")
        return True
    else:
        # Directus update failed - invalidate cache to force fresh read on next call
        try:
            await self.cache.delete(cache_key)
            logger.warning(f"Directus update failed, invalidated cache for user {user_id}")
        except Exception as cache_error:
            logger.warning(f"Failed to invalidate cache after Directus failure for user {user_id}: {cache_error}")
        
        # Detailed error logging is handled within _make_api_request.
        logger.error(f"Failed to update user {user_id} after all retries.")
        return False
