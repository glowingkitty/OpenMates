import logging

logger = logging.getLogger(__name__)

async def update_user(self, user_id: str, update_data: dict) -> bool:
    """
    Update a user's data in Directus using the centralized _make_api_request method.
    
    Parameters:
    - user_id: ID of the user to update
    - update_data: Dictionary of fields to update
    
    Returns:
    - bool: True if the update was successful, False otherwise
    """
    logger.debug(f"Attempting to update user {user_id} in Directus.")

    # The _make_api_request method handles authentication, retries, and error logging.
    # We just need to call it with the correct parameters.
    
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
        # Detailed error logging is handled within _make_api_request.
        # We can add a final confirmation of failure here.
        logger.error(f"Failed to update user {user_id} after all retries.")
        return False
