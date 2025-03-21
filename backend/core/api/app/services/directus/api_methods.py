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
            async with httpx.AsyncClient() as client:
                response = await getattr(client, method.lower())(url, headers=headers, **kwargs)
                
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
