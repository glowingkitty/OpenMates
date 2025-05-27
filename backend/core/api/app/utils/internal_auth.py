# backend/core/api/app/utils/internal_auth.py
#
# This module provides a dependency for verifying internal service tokens
# for securing internal API endpoints.

import os
from fastapi import Request, HTTPException, status, Depends
import logging

logger = logging.getLogger(__name__)

# This token should be set in the environment of the main API service.
# It's the token that incoming requests from other internal services (apps) must present.
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")

if not INTERNAL_API_SHARED_TOKEN:
    logger.critical(
        "CRITICAL SECURITY RISK: INTERNAL_API_SHARED_TOKEN is not set in the environment. "
        "Internal API endpoints will not be properly secured. "
        "Please set this variable to a strong, unique secret shared among internal services."
    )

async def verify_internal_token(request: Request):
    """
    FastAPI dependency to verify the X-Internal-Service-Token.
    Raises HTTPException if the token is invalid, missing, or if the server
    is not configured to verify tokens.
    """
    if not INTERNAL_API_SHARED_TOKEN:
        # If the main API doesn't have a token configured, it cannot verify.
        # This is a critical misconfiguration.
        logger.error("Internal API call attempt, but INTERNAL_API_SHARED_TOKEN is not configured on the API server. Denying request.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal API security token not configured on API server. Cannot authenticate request."
        )

    token = request.headers.get("X-Internal-Service-Token")
    if not token:
        logger.warning("Internal API call attempt without X-Internal-Service-Token header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # Use 401 for missing token
            detail="Missing internal service token (X-Internal-Service-Token)."
        )
    
    if token != INTERNAL_API_SHARED_TOKEN:
        logger.warning("Internal API call attempt with an invalid X-Internal-Service-Token.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal service token."
        )
    # If token is valid, proceed
    return True

# Convenience dependency for routes that need it
VerifiedInternalRequest = Depends(verify_internal_token)