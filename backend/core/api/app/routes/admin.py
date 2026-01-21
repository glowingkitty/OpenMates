# backend/core/api/app/routes/admin.py
"""
REST API endpoints for server administration functionality.
"""

import logging
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
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
    follow_up_suggestions: List[str] = []

class RejectSuggestionRequest(BaseModel):
    """Request model for rejecting a community suggestion"""
    chat_id: str

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
    made into demo chats yet. Includes the decrypted encryption key so
    admins can approve without needing to open the chat first.
    """
    try:
        # 1. Get all chats shared with community (include shared_encrypted_chat_key for approval)
        params = {
            "filter": {
                "share_with_community": {"_eq": True}
            },
            "fields": "id,encrypted_title,shared_encrypted_title,shared_encrypted_summary,shared_encrypted_category,shared_encrypted_icon,shared_encrypted_follow_up_suggestions,shared_encrypted_chat_key,updated_at,is_private,is_shared"
        }
        community_chats = await directus_service.get_items("chats", params)

        # 2. Get all existing demo chats to filter them out
        active_demos = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=False)
        existing_demo_chat_ids = {d.get("original_chat_id") for d in active_demos}

        # 3. Filter and format suggestions
        encryption_service: EncryptionService = request.app.state.encryption_service
        shared_vault_key = "shared-content-metadata"

        suggestions = []
        for chat in community_chats:
            chat_id = str(chat.get("id"))
            if chat_id in existing_demo_chat_ids:
                continue

            # Ensure chat is actually shared (double check)
            if chat.get("is_private", True):
                continue

            # Decrypt shared metadata using vault key
            # NOTE: decrypt() returns Optional[str], not a tuple
            title = None
            if chat.get("shared_encrypted_title"):
                try:
                    title = await encryption_service.decrypt(chat.get("shared_encrypted_title"), key_name=shared_vault_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt shared title for chat {chat_id}: {e}")

            summary = None
            if chat.get("shared_encrypted_summary"):
                try:
                    summary = await encryption_service.decrypt(chat.get("shared_encrypted_summary"), key_name=shared_vault_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt shared summary for chat {chat_id}: {e}")

            category = None
            if chat.get("shared_encrypted_category"):
                try:
                    category = await encryption_service.decrypt(chat.get("shared_encrypted_category"), key_name=shared_vault_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt shared category for chat {chat_id}: {e}")

            icon = None
            if chat.get("shared_encrypted_icon"):
                try:
                    icon = await encryption_service.decrypt(chat.get("shared_encrypted_icon"), key_name=shared_vault_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt shared icon for chat {chat_id}: {e}")

            follow_up_suggestions = []
            if chat.get("shared_encrypted_follow_up_suggestions"):
                try:
                    import json
                    decrypted_follow_ups = await encryption_service.decrypt(chat.get("shared_encrypted_follow_up_suggestions"), key_name=shared_vault_key)
                    if decrypted_follow_ups:
                        follow_up_suggestions = json.loads(decrypted_follow_ups)
                except Exception as e:
                    logger.warning(f"Failed to decrypt shared follow-up suggestions for chat {chat_id}: {e}")

            # Decrypt the chat encryption key (needed for demo chat approval)
            # This key was stored when the user shared the chat with community
            encryption_key = None
            if chat.get("shared_encrypted_chat_key"):
                try:
                    encryption_key = await encryption_service.decrypt(chat.get("shared_encrypted_chat_key"), key_name=shared_vault_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt shared chat key for chat {chat_id}: {e}")

            suggestions.append({
                "chat_id": chat_id,
                "title": title or "Untitled Chat",
                "summary": summary,
                "category": category,
                "icon": icon,
                "follow_up_suggestions": follow_up_suggestions,
                "shared_at": chat.get("updated_at"),
                "share_link": f"/share/chat/{chat_id}",
                "encryption_key": encryption_key  # Decrypted key for immediate approval
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
            follow_up_suggestions=payload.follow_up_suggestions,
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

@router.post("/reject-suggestion")
@limiter.limit("30/minute")
async def reject_suggestion(
    request: Request,
    payload: RejectSuggestionRequest,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Reject a community suggestion.
    This sets share_with_community to False for the specified chat.
    """
    try:
        # Verify the chat exists
        chat = await directus_service.chat.get_chat_metadata(payload.chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Update the chat to remove from community suggestions
        success = await directus_service.update_item(
            "chats", 
            payload.chat_id, 
            {"share_with_community": False}
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to reject suggestion")

        logger.info(f"Admin {admin_user.id} rejected community suggestion for chat {payload.chat_id}")

        return {
            "success": True,
            "message": "Suggestion rejected successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting community suggestion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reject suggestion")

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

@router.get("/server-stats")
@limiter.limit("30/minute")
async def get_server_stats(
    request: Request,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get server statistics for the admin dashboard.
    Returns daily stats for the last 30 days and monthly stats for the last 12 months.
    """
    try:
        from datetime import datetime
        
        # 1. Fetch last 30 daily records
        daily_stats = await directus_service.get_items(
            "server_stats_global_daily",
            params={
                "sort": "-date",
                "limit": 30
            }
        )

        # 2. Fetch last 12 monthly records
        monthly_stats = await directus_service.get_items(
            "server_stats_global_monthly",
            params={
                "sort": "-year_month",
                "limit": 12
            }
        )

        # 3. Get current totals (from latest daily record or live from Directus if needed)
        # We prefer the latest daily record as it's pre-aggregated
        current_stats = daily_stats[0] if daily_stats else {}

        return {
            "current": current_stats,
            "daily_history": daily_stats,
            "monthly_history": monthly_stats,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error fetching server stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch server statistics")
