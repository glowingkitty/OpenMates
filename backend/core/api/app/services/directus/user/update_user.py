import logging

logger = logging.getLogger(__name__)

async def update_user(self, user_id: str, update_data: dict) -> bool:
    """
    Update a user's data in Directus using the centralized _make_api_request method.
    CACHE-FIRST STRATEGY: Updates cache first, then Directus.
    Cache is the source of truth for reads, Directus is for persistence.
    
    Parameters:
    - user_id: ID of the user to update
    - update_data: Dictionary of fields to update
    
    Returns:
    - bool: True if the update was successful, False otherwise
    """
    logger.debug(f"Attempting to update user {user_id} in Directus.")

    # Step 1: CACHE-FIRST - Update cache FIRST with new data
    # This ensures cache is always the source of truth for reads
    # Cache is updated even if it doesn't exist yet (creates minimal entry)
    cache_key = f"{self.cache.USER_KEY_PREFIX}{user_id}"
    try:
        # Try to get existing cache data
        existing_cache = await self.cache.get(cache_key)
        
        if existing_cache and isinstance(existing_cache, dict):
            # Cache exists - update it with new data
            existing_cache.update(update_data)
            await self.cache.set(cache_key, existing_cache, ttl=self.cache.USER_TTL)
            logger.debug(f"Updated existing cache FIRST for user {user_id} with fields: {list(update_data.keys())}")
        else:
            # Cache doesn't exist - create minimal entry with just the update data
            # This ensures cache-first strategy: cache is always updated before Directus
            # Include user_id in the cache entry for consistency
            minimal_cache_entry = {"user_id": user_id, "id": user_id, **update_data}
            await self.cache.set(cache_key, minimal_cache_entry, ttl=self.cache.USER_TTL)
            logger.debug(f"Created new cache entry FIRST for user {user_id} with fields: {list(update_data.keys())}")
    except Exception as cache_error:
        logger.warning(f"Failed to update cache for user {user_id}: {cache_error}")
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
