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
    demo_id: str  # The demo_id of the pending demo_chat entry
    chat_id: str  # The original chat_id (for verification)
    encryption_key: str  # Encryption key from share link - required for non-auth users to decrypt
    title: str
    summary: str = ""
    category: str = ""
    follow_up_suggestions: List[str] = []

class RejectSuggestionRequest(BaseModel):
    """Request model for rejecting a community suggestion"""
    demo_id: str  # The demo_id of the pending demo_chat entry
    chat_id: str  # The original chat_id (for updating the chats table)

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

    Returns demo_chats entries with status='waiting_for_confirmation'.
    These are chats that were shared with the community and are pending admin approval.
    The metadata is decrypted using the demo_chats vault key for display.
    """
    try:
        import json
        from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
        
        # Get all pending demo chats (status='waiting_for_confirmation')
        pending_demos = await directus_service.demo_chat.get_pending_demo_chats()
        
        encryption_service: EncryptionService = request.app.state.encryption_service
        
        suggestions = []
        for demo in pending_demos:
            demo_id = demo.get("demo_id")
            chat_id = demo.get("original_chat_id")
            
            # Decrypt metadata using demo_chats vault key
            title = None
            if demo.get("encrypted_title"):
                try:
                    title = await encryption_service.decrypt(
                        demo.get("encrypted_title"), 
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt title for pending demo {demo_id}: {e}")
            
            summary = None
            if demo.get("encrypted_summary"):
                try:
                    summary = await encryption_service.decrypt(
                        demo.get("encrypted_summary"), 
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt summary for pending demo {demo_id}: {e}")
            
            category = None
            if demo.get("encrypted_category"):
                try:
                    category = await encryption_service.decrypt(
                        demo.get("encrypted_category"), 
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt category for pending demo {demo_id}: {e}")
            
            icon = None
            if demo.get("encrypted_icon"):
                try:
                    icon = await encryption_service.decrypt(
                        demo.get("encrypted_icon"), 
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt icon for pending demo {demo_id}: {e}")
            
            follow_up_suggestions = []
            if demo.get("encrypted_follow_up_suggestions"):
                try:
                    decrypted_follow_ups = await encryption_service.decrypt(
                        demo.get("encrypted_follow_up_suggestions"), 
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                    if decrypted_follow_ups:
                        follow_up_suggestions = json.loads(decrypted_follow_ups)
                except Exception as e:
                    logger.warning(f"Failed to decrypt follow-up suggestions for pending demo {demo_id}: {e}")
            
            # The encryption key is stored directly (not encrypted with vault key)
            # It's the chat encryption key needed for demo chat translation
            encryption_key = demo.get("encrypted_key")
            
            suggestions.append({
                "demo_id": demo_id,
                "chat_id": chat_id,
                "title": title or "Untitled Chat",
                "summary": summary,
                "category": category,
                "icon": icon,
                "follow_up_suggestions": follow_up_suggestions,
                "shared_at": demo.get("created_at"),
                "share_link": f"/share/chat/{chat_id}",
                "encryption_key": encryption_key,  # The chat encryption key for approval
                "status": demo.get("status")
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
    Approve a pending demo chat for translation and publication.

    Updates an existing demo_chat entry (status='waiting_for_confirmation') to
    status='translating' and triggers the translation task.
    
    Enforces a limit of 5 published demo chats - if at limit, deactivates the oldest.
    """
    try:
        from datetime import datetime, timezone
        
        # Verify the pending demo_chat exists
        demo_chat = await directus_service.demo_chat.get_demo_chat_by_id(payload.demo_id)
        if not demo_chat:
            raise HTTPException(status_code=404, detail="Demo chat not found")
        
        # Verify it's in pending status
        if demo_chat.get("status") != "waiting_for_confirmation":
            raise HTTPException(
                status_code=400, 
                detail=f"Demo chat is not pending approval (current status: {demo_chat.get('status')})"
            )
        
        # Verify the chat_id matches
        if demo_chat.get("original_chat_id") != payload.chat_id:
            raise HTTPException(status_code=400, detail="Chat ID mismatch")
        
        # Verify the original chat exists and is shared
        chat = await directus_service.chat.get_chat_metadata(payload.chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Original chat not found")
        
        if chat.get("is_private", True):
            raise HTTPException(status_code=400, detail="Chat is not publicly shared")
        
        # Check current published demo chat count and remove oldest if at limit
        current_demos = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=True)
        if len(current_demos) >= 5:
            # Sort by approved_at (or created_at as fallback) and remove the oldest
            current_demos.sort(key=lambda x: x.get("approved_at") or x.get("created_at", ""))
            oldest_demo = current_demos[0]
            await directus_service.demo_chat.deactivate_demo_chat(oldest_demo["demo_id"])
            logger.info(f"Deactivated oldest demo chat {oldest_demo['demo_id']} to make room for new demo")
        
        # Update the demo_chat entry: status -> 'translating', approved_by_admin -> true
        # Also store the title/summary for the translation table
        demo_item_id = demo_chat.get("id")
        updates = {
            "status": "translating",
            "approved_by_admin": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "encrypted_key": payload.encryption_key  # Update in case it changed
        }
        
        result = await directus_service.update_item("demo_chats", demo_item_id, updates)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to update demo chat status")
        
        # Create initial English translation entry for immediate display
        # This will be overwritten by the translation task with all languages
        initial_translation = {
            "demo_id": payload.demo_id,
            "language": "en",
            "title": payload.title,
            "summary": payload.summary,
            "follow_up_suggestions": payload.follow_up_suggestions
        }
        await directus_service.create_item("demo_chat_translations", initial_translation)
        
        # Trigger translation task
        from backend.core.api.app.tasks.demo_tasks import translate_demo_chat_task
        translate_demo_chat_task.delay(payload.demo_id)
        
        logger.info(f"Admin {admin_user.id} approved demo chat {payload.demo_id} for chat {payload.chat_id}. Translation task triggered.")
        
        return {
            "success": True,
            "demo_id": payload.demo_id,
            "message": "Demo chat approved and translation process started"
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
    Reject a pending community suggestion.
    
    This deactivates the pending demo_chat entry and sets share_with_community 
    to False on the original chat so it won't be re-submitted.
    """
    try:
        # Deactivate the pending demo_chat entry
        success = await directus_service.demo_chat.deactivate_demo_chat(payload.demo_id)
        if not success:
            raise HTTPException(status_code=404, detail="Demo chat not found or already deactivated")
        
        # Also update the original chat to remove from community suggestions
        # This prevents it from being re-submitted
        await directus_service.update_item(
            "chats", 
            payload.chat_id, 
            {"share_with_community": False}
        )
        
        logger.info(f"Admin {admin_user.id} rejected community suggestion demo_id={payload.demo_id} for chat {payload.chat_id}")
        
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
        # Get language for enrichment
        lang = request.query_params.get("lang", "en")
        demo_chats = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=False)
        
        # Enrich with language-specific metadata
        enriched_demos = []
        for demo in demo_chats:
            translation = await directus_service.demo_chat.get_demo_chat_translation(demo["demo_id"], lang)
            if not translation and lang != "en":
                translation = await directus_service.demo_chat.get_demo_chat_translation(demo["demo_id"], "en")
            
            if translation:
                demo["title"] = translation.get("title")
                demo["summary"] = translation.get("summary")
            enriched_demos.append(demo)

        return {
            "demo_chats": enriched_demos,
            "count": len(enriched_demos),
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
