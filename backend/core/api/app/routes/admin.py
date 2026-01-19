# backend/core/api/app/routes/admin.py
"""
REST API endpoints for server administration functionality.
"""

import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/admin",
    tags=["Admin"]
)

# --- Dependency to get services from app.state ---

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service

async def require_admin(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> User:
    """Dependency to ensure user has admin privileges"""
    is_admin = await directus_service.admin.is_user_admin(current_user.id)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

# --- Request/Response Models ---

class BecomeAdminRequest(BaseModel):
    """Request model for becoming admin using token"""
    token: str

class ApproveDemoChatRequest(BaseModel):
    """Request model for approving a demo chat"""
    chat_id: str
    encryption_key: str  # Encryption key from share link - required for non-auth users to decrypt
    title: str
    summary: str = ""
    category: str = ""

# --- Endpoints ---

@router.post("/become-admin")
@limiter.limit("5/minute")  # Strict rate limiting for admin creation
async def become_admin(
    request: Request,
    payload: BecomeAdminRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Grant admin privileges using a temporary token.

    This endpoint is used by the /settings/server/become-admin route
    when a server admin uses the docker exec command to generate an admin token.
    """
    try:
        # Validate the admin token
        is_valid = await directus_service.admin.validate_admin_token(payload.token)
        if not is_valid:
            logger.warning(f"Invalid admin token used by user {current_user.id}")
            raise HTTPException(status_code=400, detail="Invalid or expired admin token")

        # Grant admin privileges
        success = await directus_service.admin.make_user_admin(current_user.id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to grant admin privileges")

        logger.info(f"Granted admin privileges to user {current_user.id}")

        return {
            "success": True,
            "message": "Admin privileges granted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in become admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process admin request")

@router.get("/community-suggestions")
@limiter.limit("30/minute")
async def get_community_suggestions(
    request: Request,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get pending community chat suggestions for admin review.

    Returns chats that were shared with the community but haven't been
    made into demo chats yet.
    """
    try:
        # 1. Get all chats shared with community
        params = {
            "filter": {
                "share_with_community": {"_eq": True}
            },
            "fields": "id,encrypted_title,shared_encrypted_title,shared_encrypted_summary,updated_at,is_private,is_shared"
        }
        community_chats = await directus_service.get_items("chats", params)

        # 2. Get all existing demo chats to filter them out
        active_demos = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=False)
        existing_demo_chat_ids = {d.get("original_chat_id") for d in active_demos}

        # 3. Filter and format suggestions
        suggestions = []
        for chat in community_chats:
            chat_id = str(chat.get("id"))
            if chat_id in existing_demo_chat_ids:
                continue

            # Ensure chat is actually shared (double check)
            if chat.get("is_private", True):
                continue

            # Get title and summary (fall back to encrypted_title if shared versions missing)
            # Note: Server can decrypt shared_* fields using shared vault key
            # but for the suggestion list we just need metadata
            suggestions.append({
                "chat_id": chat_id,
                "title": chat.get("encrypted_title"), # This will be decrypted on client if needed
                "summary": None, # Will be fetched/decrypted on client
                "shared_at": chat.get("updated_at"),
                "share_link": f"/share/chat/{chat_id}" # UI will add the key from the email or local store
            })

        return {
            "suggestions": suggestions,
            "count": len(suggestions)
        }

    except Exception as e:
        logger.error(f"Error getting community suggestions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get community suggestions")

@router.post("/approve-demo-chat")
@limiter.limit("10/hour")  # Limit demo chat approvals
async def approve_demo_chat(
    request: Request,
    payload: ApproveDemoChatRequest,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Approve a community-shared chat to become a demo chat.

    This creates a demo chat entry with a limit of 5 most recent demos.
    """
    try:
        # Verify the chat exists and is shared
        chat = await directus_service.chat.get_chat_metadata(payload.chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        if chat.get("is_private", True):
            raise HTTPException(status_code=400, detail="Chat is not publicly shared")

        # Use the encryption key provided in the request
        # This key comes from the share link and allows non-authenticated users to decrypt the chat
        # SECURITY: Each chat has its own encryption key, so storing it for demo chats is safe
        # - The key only decrypts this specific chat
        # - Even if compromised, it only affects this one demo chat
        # - Demo chats are public content by design (admin-approved for public display)
        encryption_key = payload.encryption_key

        # Check current demo chat count and remove oldest if at limit
        current_demos = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=True)
        if len(current_demos) >= 5:
            # Sort by created_at and remove the oldest
            current_demos.sort(key=lambda x: x.get("created_at", ""))
            oldest_demo = current_demos[0]
            await directus_service.demo_chat.deactivate_demo_chat(oldest_demo["demo_id"])
            logger.info(f"Deactivated oldest demo chat {oldest_demo['demo_id']} to make room for new demo")

        # Create the demo chat
        demo_chat = await directus_service.demo_chat.create_demo_chat(
            chat_id=payload.chat_id,
            encryption_key=encryption_key,
            title=payload.title,
            summary=payload.summary,
            category=payload.category,
            approved_by_admin=True
        )

        if not demo_chat:
            raise HTTPException(status_code=500, detail="Failed to create demo chat")

        logger.info(f"Admin {admin_user.id} approved demo chat for chat {payload.chat_id}")

        return {
            "success": True,
            "demo_id": demo_chat.get("demo_id"),
            "message": "Demo chat approved and created successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving demo chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to approve demo chat")

@router.get("/demo-chats")
@limiter.limit("30/minute")
async def get_admin_demo_chats(
    request: Request,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get all demo chats for admin management.
    """
    try:
        demo_chats = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=False)

        return {
            "demo_chats": demo_chats,
            "count": len(demo_chats),
            "limit": 5
        }

    except Exception as e:
        logger.error(f"Error getting admin demo chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get demo chats")

@router.delete("/demo-chat/{demo_id}")
@limiter.limit("10/hour")
async def delete_demo_chat(
    request: Request,
    demo_id: str,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Deactivate a demo chat.
    """
    try:
        success = await directus_service.demo_chat.deactivate_demo_chat(demo_id)
        if not success:
            raise HTTPException(status_code=404, detail="Demo chat not found")

        logger.info(f"Admin {admin_user.id} deactivated demo chat {demo_id}")

        return {
            "success": True,
            "message": "Demo chat deactivated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting demo chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete demo chat")