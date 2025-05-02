import httpx
import logging
import asyncio
from fastapi import HTTPException

logger = logging.getLogger(__name__)

async def _make_api_request(self, method, url, headers=None, **kwargs):
    """Make an API request with token refresh capability"""
    headers = headers or {}
    
    for attempt in range(self.max_retries):
        if attempt > 0:
            logger.info(f"Retry attempt {attempt} for {method} {url}")
        
        # Get a fresh token if this is a retry
        token = await self.ensure_auth_token(force_refresh=(attempt > 0))
        if not token:
            raise HTTPException(status_code=500, detail="Failed to authenticate with CMS")
        
        headers["Authorization"] = f"Bearer {token}"
        
        try:
            # Define timeout per attempt (consistent with update_user)
            request_timeout = 3.0
            async with httpx.AsyncClient() as client:
                response = await getattr(client, method.lower())(
                    url,
                    headers=headers,
                    timeout=request_timeout,  # Add explicit timeout here
                    **kwargs
                )
                
                if response.status_code == 401 and "TOKEN_EXPIRED" in response.text:
                    if attempt < self.max_retries - 1:
                        logger.warning("Token expired, will refresh and retry")
                        await self.clear_tokens()
                        continue
                
                return response
                
        except Exception as e:
            if attempt < self.max_retries - 1:
                logger.warning(f"Request failed: {str(e)}. Retrying...")
                await asyncio.sleep(1)  # Add a small delay before retrying
            else:
                raise e
    
    # This should never happen because of the exception above, but just in case
    raise HTTPException(status_code=500, detail="Maximum retry attempts reached")


async def create_item(self, collection: str, payload: dict):
   """
   Creates a new item in a specified Directus collection.

   Args:
       self: The DirectusService instance.
       collection: The name of the collection to create the item in.
       payload: A dictionary containing the item data to be created.

   Returns:
       A tuple (bool, dict): (True, created_item_data) on success,
                              (False, error_details) on failure.
   """
   url = f"{self.base_url}/items/{collection}"
   logger.info(f"Attempting to create item in collection '{collection}'")

   try:
       # Use the internal _make_api_request helper for the POST request
       response = await self._make_api_request("POST", url, json=payload)

       # Check if the request was successful (status code 2xx)
       if 200 <= response.status_code < 300:
           created_item = response.json().get("data")
           logger.info(f"Successfully created item in '{collection}'. ID: {created_item.get('id') if created_item else 'N/A'}")
           return True, created_item
       else:
           # Log error if creation failed
           error_details = {"status_code": response.status_code, "text": response.text}
           logger.error(f"Failed to create item in '{collection}'. Status: {response.status_code}, Response: {response.text}")
           return False, error_details

   except Exception as e:
       # Log any exception during the process
       logger.error(f"Exception during item creation in '{collection}': {str(e)}", exc_info=True)
       return False, {"error": str(e)}
