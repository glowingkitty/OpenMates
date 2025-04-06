import os
from typing import Optional
from fastapi import HTTPException, Cookie, Depends
import logging

logger = logging.getLogger(__name__)

# Load the admin access key from environment variables once
ADMIN_ACCESS_KEY = os.getenv("ADMIN_ACCESS_KEY")

async def verify_admin_access_key(admin_access_token: Optional[str] = Cookie(None, description="Admin access token cookie required for this endpoint")):
    """
    FastAPI dependency to verify the admin access key provided in the 'admin_access_token' cookie.

    Raises:
        HTTPException(500): If the ADMIN_ACCESS_KEY environment variable is not set.
        HTTPException(401): If the provided token does not match the environment variable or is missing.
    """
    if not ADMIN_ACCESS_KEY:
        logger.error("CRITICAL: ADMIN_ACCESS_KEY environment variable is not set!")
        raise HTTPException(status_code=500, detail="Internal server error: Admin access key not configured.")

    if admin_access_token is None:
        logger.warning("Admin access token cookie missing in request.")
        raise HTTPException(status_code=401, detail="Unauthorized: Access token cookie required.")

    if admin_access_token != ADMIN_ACCESS_KEY:
        logger.warning("Invalid admin access token cookie provided.")
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid access token cookie.")

    # If tokens match, the request can proceed
    logger.debug("Admin access token cookie verified successfully.")
    return True # Indicate success (though the return value isn't typically used)