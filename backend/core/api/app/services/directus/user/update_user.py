import logging
import asyncio
import aiohttp
import json
from aiohttp import ClientTimeout, ClientError

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
    max_retries = 3
    retry_delay = 1  # seconds

    try:
        logger.debug(f"Attempting to update user {user_id} in Directus.")

        # Ensure we have admin token (outside retry loop, as failure here is likely persistent)
        await self.ensure_auth_token(admin_required=True)
        if not self.admin_token:
            logger.error("Failed to get admin token for user update")
            return False

        url = f"{self.base_url}/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json"
        }
        timeout = ClientTimeout(total=3)  # Set a 3-second total timeout per attempt

        for attempt in range(max_retries):
            try:
                logger.debug(f"Update user {user_id} attempt {attempt + 1}/{max_retries}")
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.patch(url, headers=headers, json=update_data) as response:
                        if response.status == 200:
                            logger.info(f"Successfully updated user {user_id} in Directus.")
                            return True
                        else:
                            # Log non-200 status but don't retry unless it's a specific retryable error caught below
                            error_text = await response.text()
                            logger.error(f"Failed update attempt {attempt + 1} for user {user_id}. Status: {response.status}, Response: {error_text}")
                            # Decide if status is retryable (e.g., 5xx, 408). For now, let's only retry on explicit exceptions.
                            # If it's a 4xx error (like 400 Bad Request), retrying won't help.
                            if 400 <= response.status < 500 and response.status != 408: # Don't retry client errors (except maybe 408)
                                logger.warning(f"Non-retryable status {response.status} received for user {user_id}. Aborting.")
                                return False
                            # Fall through to potentially retry for 5xx or 408 if not caught by specific exceptions

            except (asyncio.TimeoutError, ClientError) as e:
                logger.warning(f"Update attempt {attempt + 1} failed for user {user_id} due to {type(e).__name__}: {str(e)}")
                if attempt + 1 == max_retries:
                    logger.error(f"All {max_retries} update attempts failed for user {user_id}.")
                    return False # All retries failed
                logger.info(f"Retrying update for user {user_id} in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                continue # Go to the next attempt

            # If we got here with a non-200 status that wasn't a client error (e.g. 5xx)
            # and wasn't caught as Timeout/ClientError, decide whether to retry or fail.
            # Let's retry for now, assuming it might be transient.
            if attempt + 1 < max_retries:
                 logger.info(f"Retrying update for user {user_id} after status {response.status} in {retry_delay} seconds...")
                 await asyncio.sleep(retry_delay)
            else:
                 logger.error(f"Update for user {user_id} failed after {max_retries} attempts with final status {response.status}.")
                 return False # Failed after retries

        # This part should ideally not be reached if logic is correct, but acts as a fallback.
        logger.error(f"Update logic completed for user {user_id} without returning success/failure after retries.")
        return False

    except Exception as e:
        # Catch errors outside the retry loop (e.g., ensure_auth_token failure)
        logger.error(f"Unhandled error during update process for user {user_id}: {str(e)}")
        return False