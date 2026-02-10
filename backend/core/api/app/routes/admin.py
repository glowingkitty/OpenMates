# backend/core/api/app/routes/admin.py
"""
REST API endpoints for server administration functionality.
"""

import logging
import random
import string
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator

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
    demo_chat_id: str  # UUID of the demo_chats entry
    chat_id: str  # The original chat_id (for verification)
    replace_demo_chat_id: str | None = None  # Optional: UUID of demo chat to replace (if at limit)
    demo_chat_category: str = "for_everyone"  # Target audience: "for_everyone" (default, max 6) or "for_developers" (max 4)

class UpdateDemoChatCategoryRequest(BaseModel):
    """Request model for updating a demo chat's category"""
    demo_chat_category: str  # New category: "for_everyone" or "for_developers"

class RejectSuggestionRequest(BaseModel):
    """Request model for rejecting a community suggestion"""
    demo_chat_id: str  # UUID of the demo_chats entry
    chat_id: str  # The original chat_id (for updating the chats table)

class GenerateGiftCardsRequest(BaseModel):
    """Request model for admin gift card generation.
    
    Allows admins to generate one or more gift card codes with a specified
    credit value, optional custom prefix (replaces first segment of XXXX-XXXX-XXXX),
    and optional admin notes.
    """
    credits_value: int = Field(..., ge=1, le=50000, description="Credit value for each gift card (1-50,000)")
    count: int = Field(default=1, ge=1, le=100, description="Number of gift cards to generate (1-100)")
    prefix: Optional[str] = Field(default=None, max_length=4, description="Optional custom prefix (max 4 chars, replaces first segment)")
    notes: Optional[str] = Field(default=None, max_length=500, description="Optional admin notes for these gift cards")

    @field_validator('prefix')
    @classmethod
    def validate_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == '':
            return None
        v = v.upper().strip()
        # Charset must match the gift card generation charset:
        # Uppercase letters (excluding O, I) + digits (excluding 0, 1)
        valid_charset = set(
            string.ascii_uppercase.replace('O', '').replace('I', '')
            + string.digits.replace('0', '').replace('1', '')
        )
        if not all(c in valid_charset for c in v):
            raise ValueError(
                'Prefix must only contain uppercase letters (A-Z excluding O, I) '
                'and digits (2-9). Ambiguous characters (0, O, I, 1) are not allowed.'
            )
        if len(v) < 1 or len(v) > 4:
            raise ValueError('Prefix must be 1-4 characters long')
        return v

class GenerateGiftCardsResponse(BaseModel):
    """Response model for admin gift card generation."""
    success: bool
    gift_cards: List[Dict[str, Any]]  # List of {code, credits_value, created_at}
    count: int
    message: str

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

    Returns demo_chats entries with status='pending_approval'.
    These are chats that were shared with the community and are pending admin approval.
    The metadata is decrypted using the demo_chats vault key for display.
    """
    try:
        import json
        
        # Get all pending demo chats (status='pending_approval')
        pending_demos = await directus_service.demo_chat.get_pending_demo_chats()
        
        suggestions = []
        for demo in pending_demos:
            demo_chat_item = demo  # demo is already the full item with 'id' field
            chat_id = demo.get("original_chat_id")
            
            # Get metadata from cleartext fields
            title = demo.get("title")
            summary = demo.get("summary")
            category = demo.get("category")
            icon = demo.get("icon")
            
            # Parse follow-up suggestions from cleartext JSON
            follow_up_suggestions = []
            if demo.get("follow_up_suggestions"):
                try:
                    follow_up_suggestions = json.loads(demo["follow_up_suggestions"])
                except Exception as e:
                    logger.warning(f"Failed to parse follow-up suggestions for pending demo {demo_chat_item['id']}: {e}")
            
            # No encryption_key field anymore with zero-knowledge architecture
            encryption_key = None
            
            suggestions.append({
                "demo_chat_id": demo_chat_item["id"],  # UUID of the demo_chats entry
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

    Updates an existing demo_chat entry (status='pending_approval') to
    status='translating' and triggers the translation task.
    
    Enforces a limit of 10 published demo chats total (6 for_everyone + 4 for_developers).
    Admin selects the demo_chat_category ("for_everyone" or "for_developers") during approval.
    """
    try:
        from datetime import datetime, timezone
        
        # Validate demo_chat_category
        if payload.demo_chat_category not in ("for_everyone", "for_developers"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid demo_chat_category: {payload.demo_chat_category}. Must be 'for_everyone' or 'for_developers'."
            )
        
        # Category-specific limits: 6 for "for_everyone", 4 for "for_developers"
        CATEGORY_LIMITS = {"for_everyone": 6, "for_developers": 4}
        category_limit = CATEGORY_LIMITS[payload.demo_chat_category]
        
        # Verify the pending demo_chat exists (payload.demo_chat_id is the UUID)
        demo_chats = await directus_service.get_items("demo_chats", {
            "filter": {"id": {"_eq": payload.demo_chat_id}},
            "limit": 1
        })
        demo_chat = demo_chats[0] if demo_chats else None
        if not demo_chat:
            raise HTTPException(status_code=404, detail="Demo chat not found")
        
        # Verify it's in pending status
        if demo_chat.get("status") != "pending_approval":
            raise HTTPException(
                status_code=400, 
                detail=f"Demo chat is not pending approval (current status: {demo_chat.get('status')})"
            )
        
        # Verify the chat_id matches the demo_chat entry
        if demo_chat.get("original_chat_id") != payload.chat_id:
            raise HTTPException(status_code=400, detail="Chat ID mismatch")

        # Note: No need to verify the original chat still exists.
        # The demo_chat entry already contains all content needed for translation,
        # independent of whether the original user chat was deleted.

        # Check current published demo chat count for the selected category
        # Query Directus directly to avoid cache format issues
        current_demos = await directus_service.get_items("demo_chats", {
            "filter": {
                "is_active": {"_eq": True},
                "status": {"_eq": "published"}
            },
            "sort": "-created_at"
        })
        current_demos = current_demos or []
        # Filter demos by the target category
        category_demos = [d for d in current_demos if d.get("demo_chat_category") == payload.demo_chat_category]
        
        if len(category_demos) >= category_limit:
            # Determine which demo to replace (from the same category)
            demo_to_remove_id = None
            
            if payload.replace_demo_chat_id:
                # Admin specified which demo to replace - validate it exists in current demos
                demo_ids = [d["id"] for d in current_demos]
                if payload.replace_demo_chat_id not in demo_ids:
                    raise HTTPException(
                        status_code=400, 
                        detail="Specified replacement demo chat not found or not currently published"
                    )
                demo_to_remove_id = payload.replace_demo_chat_id
                logger.info(f"Admin selected demo chat {demo_to_remove_id} for replacement")
            else:
                # No replacement specified - fall back to oldest demo in the same category
                category_demos.sort(key=lambda x: x.get("created_at", ""))
                demo_to_remove_id = category_demos[0]["id"]
                logger.info(f"No replacement specified, defaulting to oldest '{payload.demo_chat_category}' demo chat {demo_to_remove_id}")
            
            logger.info(f"Deleting demo chat {demo_to_remove_id} to make room for new demo")
            
            # Batch delete all related data using filters
            # Note: Directus batch delete uses filter parameters
            await directus_service.delete_items("demo_messages", {"demo_chat_id": {"_eq": demo_to_remove_id}}, admin_required=True)
            await directus_service.delete_items("demo_embeds", {"demo_chat_id": {"_eq": demo_to_remove_id}}, admin_required=True)
            await directus_service.delete_items("demo_chat_translations", {"demo_chat_id": {"_eq": demo_to_remove_id}}, admin_required=True)
            
            # Finally, delete the demo_chat entry itself
            await directus_service.delete_item("demo_chats", demo_to_remove_id, admin_required=True)
            logger.info(f"Deleted demo chat {demo_to_remove_id} and all related data")
        
        # Update the demo_chat entry: status -> 'translating', approved_by_admin -> admin UUID, demo_chat_category
        updates = {
            "status": "translating",
            "approved_by_admin": admin_user.id,  # Store admin UUID
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "demo_chat_category": payload.demo_chat_category  # Store target audience category
        }
        
        result = await directus_service.update_item("demo_chats", payload.demo_chat_id, updates, admin_required=True)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to update demo chat status")
        
        # Trigger translation task (pass UUID, not demo_id string)
        from backend.core.api.app.tasks.demo_tasks import translate_demo_chat_task
        translate_demo_chat_task.delay(payload.demo_chat_id, admin_user_id=admin_user.id)
        
        logger.info(f"Admin {admin_user.id} approved demo chat {payload.demo_chat_id} for chat {payload.chat_id}. Translation task triggered.")
        
        return {
            "success": True,
            "demo_chat_id": payload.demo_chat_id,
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
    
    This deletes the pending demo_chat entry and all related data (messages, embeds, translations)
    and sets share_with_community to False on the original chat so it won't be re-submitted.
    
    CRITICAL: All related data must be deleted to prevent orphaned foreign key references.
    """
    try:
        demo_chat_id = payload.demo_chat_id
        
        logger.info(f"Admin {admin_user.id} rejecting demo_chat {demo_chat_id}")
        
        # Batch delete all related data using filters (CRITICAL: must happen BEFORE deleting demo_chat)
        # 1. Delete demo_messages
        messages_deleted = await directus_service.delete_items(
            "demo_messages",
            {"demo_chat_id": {"_eq": demo_chat_id}},
            admin_required=True
        )
        logger.info(f"Deleted {messages_deleted} demo_messages for demo_chat {demo_chat_id}")
        
        # 2. Delete demo_embeds
        embeds_deleted = await directus_service.delete_items(
            "demo_embeds",
            {"demo_chat_id": {"_eq": demo_chat_id}},
            admin_required=True
        )
        logger.info(f"Deleted {embeds_deleted} demo_embeds for demo_chat {demo_chat_id}")
        
        # 3. Delete demo_chat_translations
        translations_deleted = await directus_service.delete_items(
            "demo_chat_translations",
            {"demo_chat_id": {"_eq": demo_chat_id}},
            admin_required=True
        )
        logger.info(f"Deleted {translations_deleted} demo_chat_translations for demo_chat {demo_chat_id}")
        
        # 4. Finally, delete the demo_chat entry itself
        success = await directus_service.delete_item("demo_chats", demo_chat_id, admin_required=True)
        if not success:
            raise HTTPException(status_code=404, detail="Demo chat not found")
        
        logger.info(f"Admin {admin_user.id} deleted demo chat {demo_chat_id} and all related data")
        
        # 5. Update the original chat to remove from community suggestions
        # This prevents it from being re-submitted
        await directus_service.update_item(
            "chats", 
            payload.chat_id, 
            {"share_with_community": False}
        )
        
        logger.info(f"Admin {admin_user.id} rejected community suggestion demo_chat_id={payload.demo_chat_id} for chat {payload.chat_id}")
        
        return {
            "success": True,
            "message": "Suggestion rejected successfully",
            "deleted_counts": {
                "messages": messages_deleted,
                "embeds": embeds_deleted,
                "translations": translations_deleted
            }
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
            demo_chat_id = demo["id"]  # UUID
            
            # Get translation for this language
            translation_params = {
                "filter": {
                    "demo_chat_id": {"_eq": demo_chat_id},
                    "language": {"_eq": lang}
                },
                "limit": 1
            }
            translations = await directus_service.get_items("demo_chat_translations", translation_params)
            translation = translations[0] if translations else None
            
            # Fallback to English if translation not found
            if not translation and lang != "en":
                translation_params["filter"]["language"] = {"_eq": "en"}
                translations = await directus_service.get_items("demo_chat_translations", translation_params)
                translation = translations[0] if translations else None
            
            # Get translation metadata (stored as cleartext)
            title = None
            summary = None
            if translation:
                title = translation.get("title")
                summary = translation.get("summary")
            
            # Fallback to original metadata if translation not found
            if not title:
                title = demo.get("title")
            
            if not summary:
                summary = demo.get("summary")

            # Get category, icon, and demo_chat_category from original demo entry (stored as cleartext)
            category = demo.get("category")
            icon = demo.get("icon")
            demo_chat_category = demo.get("demo_chat_category", "for_everyone")
            
            demo["title"] = title or "Demo Chat"
            demo["summary"] = summary
            demo["category"] = category
            demo["icon"] = icon
            demo["demo_chat_category"] = demo_chat_category
            
            enriched_demos.append(demo)

        return {
            "demo_chats": enriched_demos,
            "count": len(enriched_demos),
            "limit": 10,
            "category_limits": {"for_everyone": 6, "for_developers": 4}
        }

    except Exception as e:
        logger.error(f"Error getting admin demo chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get demo chats")

@router.delete("/demo-chat/{demo_chat_id}")
@limiter.limit("10/hour")
async def delete_demo_chat(
    request: Request,
    demo_chat_id: str,  # UUID parameter
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Delete a demo chat and all related data (messages, embeds, translations).
    """
    try:
        # Batch delete all related data using filters
        await directus_service.delete_items("demo_messages", {"demo_chat_id": {"_eq": demo_chat_id}}, admin_required=True)
        await directus_service.delete_items("demo_embeds", {"demo_chat_id": {"_eq": demo_chat_id}}, admin_required=True)
        await directus_service.delete_items("demo_chat_translations", {"demo_chat_id": {"_eq": demo_chat_id}}, admin_required=True)
        
        # Finally, delete the demo_chat entry itself
        success = await directus_service.delete_item("demo_chats", demo_chat_id, admin_required=True)
        if not success:
            raise HTTPException(status_code=404, detail="Demo chat not found")

        logger.info(f"Admin {admin_user.id} deleted demo chat {demo_chat_id} and all related data")
        
        # Clear cache after deletion
        await directus_service.cache.clear_demo_chats_cache()

        return {
            "success": True,
            "message": "Demo chat deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting demo chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete demo chat")

@router.patch("/demo-chat/{demo_chat_id}/category")
@limiter.limit("30/minute")
async def update_demo_chat_category(
    request: Request,
    demo_chat_id: str,
    payload: UpdateDemoChatCategoryRequest,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Update the demo_chat_category of an existing published demo chat.
    
    Enforces per-category limits (6 for_everyone, 4 for_developers).
    If the target category is already at its limit, the request is rejected.
    """
    try:
        new_category = payload.demo_chat_category
        if new_category not in ("for_everyone", "for_developers"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid demo_chat_category: {new_category}. Must be 'for_everyone' or 'for_developers'."
            )

        # Verify the demo chat exists and is published or translating
        demo_chats = await directus_service.get_items("demo_chats", {
            "filter": {"id": {"_eq": demo_chat_id}},
            "limit": 1
        })
        demo_chat = demo_chats[0] if demo_chats else None
        if not demo_chat:
            raise HTTPException(status_code=404, detail="Demo chat not found")

        current_category = demo_chat.get("demo_chat_category", "for_everyone")
        if current_category == new_category:
            return {
                "success": True,
                "message": "Category unchanged",
                "demo_chat_category": new_category
            }

        # Check that the target category has room (excluding this demo from the count)
        # Query Directus directly to avoid cache format issues
        CATEGORY_LIMITS = {"for_everyone": 6, "for_developers": 4}
        published_demos = await directus_service.get_items("demo_chats", {
            "filter": {
                "is_active": {"_eq": True},
                "status": {"_eq": "published"},
                "demo_chat_category": {"_eq": new_category},
                "id": {"_neq": demo_chat_id}
            }
        })
        target_category_count = len(published_demos) if published_demos else 0

        if target_category_count >= CATEGORY_LIMITS[new_category]:
            raise HTTPException(
                status_code=400,
                detail=f"Category '{new_category}' is already at its limit of {CATEGORY_LIMITS[new_category]}. Remove a demo from that category first."
            )

        # Update the category
        result = await directus_service.update_item(
            "demo_chats", demo_chat_id,
            {"demo_chat_category": new_category},
            admin_required=True
        )
        if not result:
            raise HTTPException(status_code=500, detail="Failed to update demo chat category")

        # Clear cache so clients pick up the change
        await directus_service.cache.clear_demo_chats_cache()

        logger.info(f"Admin {admin_user.id} changed demo chat {demo_chat_id} category from '{current_category}' to '{new_category}'")

        return {
            "success": True,
            "message": f"Category updated to '{new_category}'",
            "demo_chat_category": new_category
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating demo chat category: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update demo chat category")

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

        # 4. Fetch newsletter subscriber count (confirmed subscribers only)
        newsletter_subscribers_count = 0
        try:
            from backend.core.api.app.routes.newsletter import get_total_newsletter_subscribers_count
            newsletter_subscribers_count = await get_total_newsletter_subscribers_count(directus_service)
        except Exception as e:
            logger.error(f"Error fetching newsletter subscribers count: {e}", exc_info=True)

        return {
            "current": current_stats,
            "daily_history": daily_stats,
            "monthly_history": monthly_stats,
            "newsletter_subscribers_count": newsletter_subscribers_count,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error fetching server stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch server statistics")


# --- Gift Card Code Generation ---
# Charset: uppercase letters (excluding ambiguous O, I) + digits (excluding ambiguous 0, 1)
# This matches the canonical charset used in payments.py for consistency
GIFT_CARD_CHARSET = (
    string.ascii_uppercase.replace('O', '').replace('I', '')
    + string.digits.replace('0', '').replace('1', '')
)


def generate_gift_card_code(prefix: Optional[str] = None) -> str:
    """
    Generate a unique gift card code in the format XXXX-XXXX-XXXX.
    Uses uppercase letters and digits, excluding ambiguous characters (0, O, I, 1).
    
    If a prefix is provided (1-4 chars), it replaces the first segment.
    The prefix is right-padded with random chars to always produce a 4-char first segment.
    Example: prefix='XM' -> 'XMAB-XXXX-XXXX'
    
    Args:
        prefix: Optional custom prefix (1-4 chars, from the valid charset)
        
    Returns:
        A gift card code string in XXXX-XXXX-XXXX format
    """
    if prefix:
        # Prefix replaces start of first segment, pad remainder with random chars
        prefix = prefix.upper()
        remaining = 4 - len(prefix)
        part1 = prefix + ''.join(random.choices(GIFT_CARD_CHARSET, k=remaining))
    else:
        part1 = ''.join(random.choices(GIFT_CARD_CHARSET, k=4))
    
    part2 = ''.join(random.choices(GIFT_CARD_CHARSET, k=4))
    part3 = ''.join(random.choices(GIFT_CARD_CHARSET, k=4))
    
    return f"{part1}-{part2}-{part3}"


@router.post("/generate-gift-cards", response_model=GenerateGiftCardsResponse)
@limiter.limit("10/minute")
async def admin_generate_gift_cards(
    request: Request,
    payload: GenerateGiftCardsRequest,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Generate one or more gift card codes with a specified credit value.
    
    Admin-only endpoint. Creates gift cards in the database and returns
    the generated codes. Supports optional custom prefix for the first
    segment of the XXXX-XXXX-XXXX format and optional admin notes.
    
    Security: Protected by require_admin dependency which validates
    the user is in the server_admins collection with is_active=True.
    """
    try:
        generated_cards: List[Dict[str, Any]] = []
        max_retries = 3  # Max retries per code in case of collision
        
        logger.info(
            f"Admin {admin_user.id} generating {payload.count} gift card(s) "
            f"with {payload.credits_value} credits each"
            f"{f', prefix={payload.prefix}' if payload.prefix else ''}"
        )
        
        for i in range(payload.count):
            # Generate a unique code, retry on collision
            code = None
            for attempt in range(max_retries):
                candidate = generate_gift_card_code(prefix=payload.prefix)
                
                # Check for collision by looking up the code
                existing = await directus_service.get_gift_card_by_code(candidate)
                if existing is None:
                    code = candidate
                    break
                else:
                    logger.warning(
                        f"Gift card code collision on attempt {attempt + 1}: {candidate}. Retrying..."
                    )
            
            if code is None:
                logger.error(f"Failed to generate unique gift card code after {max_retries} retries")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to generate unique code for card {i + 1}. Please try again."
                )
            
            # Create the gift card in Directus (no purchaser since admin-generated)
            created_card = await directus_service.create_gift_card(
                code=code,
                credits_value=payload.credits_value,
                purchaser_user_id_hash=None  # Admin-generated, not purchased
            )
            
            if not created_card:
                logger.error(f"Failed to create gift card with code: {code}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create gift card {i + 1} in database. Please try again."
                )
            
            # Add notes to the gift card if provided
            # Notes are stored directly in the gift_cards table
            if payload.notes:
                try:
                    await directus_service.update_item(
                        "gift_cards",
                        created_card["id"],
                        {"notes": payload.notes}
                    )
                except Exception as notes_err:
                    # Non-critical: log but don't fail the whole operation
                    logger.warning(f"Failed to add notes to gift card {code}: {notes_err}")
            
            generated_cards.append({
                "code": code,
                "credits_value": payload.credits_value,
                "created_at": created_card.get("created_at", "")
            })
        
        logger.info(
            f"Admin {admin_user.id} successfully generated {len(generated_cards)} gift card(s) "
            f"with {payload.credits_value} credits each"
        )
        
        return {
            "success": True,
            "gift_cards": generated_cards,
            "count": len(generated_cards),
            "message": f"Successfully generated {len(generated_cards)} gift card(s)"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating gift cards: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate gift cards")
