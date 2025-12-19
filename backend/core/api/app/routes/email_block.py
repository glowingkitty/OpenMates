"""
Email blocking routes.

This module handles blocking email addresses from receiving any emails from the system,
including signup emails, newsletter emails, and all other email communications.
"""

from fastapi import APIRouter, Depends, Request
import logging
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.utils.newsletter_utils import hash_email, check_ignored_email

router = APIRouter(
    prefix="/v1",
    tags=["Email Blocking"]
)
logger = logging.getLogger(__name__)


# Request/Response models
class BlockEmailRequest(BaseModel):
    email: EmailStr


class BlockEmailResponse(BaseModel):
    success: bool
    message: str


@router.post("/block-email", response_model=BlockEmailResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def block_email(
    request: Request,
    block_request: BlockEmailRequest,
    directus_service: DirectusService = Depends(get_directus_service),
):
    """
    Block an email address from receiving any emails from the system.
    
    This endpoint blocks emails for ALL purposes:
    - Signup confirmation emails
    - Newsletter emails
    - Security alerts
    - All other email communications
    
    The endpoint:
    1. Checks for existing newsletter subscribers with the email and deletes them
    2. Adds the email to the block list (ignored_emails)
    
    Once blocked, the email will be prevented from:
    - Signing up for new accounts
    - Receiving newsletter emails
    - Receiving any other system emails
    
    Args:
        block_request: Request containing email address to block
        
    Returns:
        BlockEmailResponse with success status and message
    """
    try:
        email = block_request.email.lower().strip()
        
        # Hash email for lookup
        hashed_email = hash_email(email)
        
        # Check if already in ignored list
        is_ignored = await check_ignored_email(hashed_email, directus_service)
        if is_ignored:
            logger.info(f"Email already in block list: {hashed_email[:16]}...")
            return BlockEmailResponse(
                success=True,
                message="This email address is already blocked and will not receive any further emails."
            )
        
        # Check for existing newsletter subscribers and delete them
        newsletter_collection = "newsletter_subscribers"
        url = f"{directus_service.base_url}/items/{newsletter_collection}"
        params = {"filter[hashed_email][_eq]": hashed_email}
        
        response = await directus_service._make_api_request("GET", url, params=params)
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            # Delete all newsletter subscriber entries for this email
            for item in items:
                subscriber_id = item.get("id")
                if subscriber_id:
                    delete_url = f"{directus_service.base_url}/items/{newsletter_collection}/{subscriber_id}"
                    delete_response = await directus_service._make_api_request("DELETE", delete_url)
                    if delete_response.status_code in [200, 204]:
                        logger.info(f"Deleted newsletter subscriber entry: {hashed_email[:16]}...")
        
        # Add to ignored_emails list
        # This blocks the email from ALL email communications, including signup
        collection_name = "ignored_emails"
        create_payload = {
            "hashed_email": hashed_email,
            "reason": "user_block_request",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        success, _ = await directus_service.create_item(collection_name, create_payload)
        
        if success:
            logger.info(f"Added email to block list: {hashed_email[:16]}...")
            return BlockEmailResponse(
                success=True,
                message="Your email address has been blocked. You will not receive any further emails from us, including signup emails."
            )
        else:
            return BlockEmailResponse(
                success=False,
                message="An error occurred while processing your block request."
            )
        
    except Exception as e:
        logger.error(f"Error blocking email: {str(e)}", exc_info=True)
        return BlockEmailResponse(
            success=False,
            message="An error occurred while processing your block request."
        )
