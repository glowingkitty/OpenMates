# backend/core/api/app/routes/demo_chat.py
"""
REST API endpoints for demo chat functionality.
Handles creation, approval, and public access to demo chats.
"""

import logging
import hashlib
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_current_user_optional
from backend.core.api.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/demo",
    tags=["Demo Chat"]
)

# --- Dependency to get services from app.state ---

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service

# --- Endpoints ---

@router.get("/chats")
@limiter.limit("60/minute")  # Public endpoint, higher rate limit
async def get_demo_chats(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get list of approved demo chats.

    This endpoint is public and can be accessed by non-authenticated users.
    Only returns approved demo chats.
    """
    try:
        # 1. Try to get from cache first
        cached_data = await directus_service.cache.get_demo_chats_list(category=category)
        if cached_data:
            # Check if this is the "public-ready" format (list of dicts with count)
            if isinstance(cached_data, dict) and "demo_chats" in cached_data:
                logger.debug(f"Cache HIT: Returning public-ready demo chats list (category: {category})")
                return cached_data

        # 2. Get from database (via service which also has internal caching)
        if category:
            demo_chats = await directus_service.demo_chat.get_demo_chats_by_category(category, approved_only=True)
        else:
            demo_chats = await directus_service.demo_chat.get_all_active_demo_chats(approved_only=True)

        # 3. Remove sensitive information before returning
        public_demo_chats = []
        for demo_chat in demo_chats:
            public_demo_chat = {
                "demo_id": demo_chat.get("demo_id"),
                "title": demo_chat.get("title"),
                "summary": demo_chat.get("summary"),
                "category": demo_chat.get("category"),
                "created_at": demo_chat.get("created_at")
            }
            public_demo_chats.append(public_demo_chat)

        response_data = {
            "demo_chats": public_demo_chats,
            "count": len(public_demo_chats)
        }

        # 4. Cache the final public-ready result
        await directus_service.cache.set_demo_chats_list(response_data, category=category)

        return response_data

    except Exception as e:
        logger.error(f"Error fetching demo chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch demo chats")

@router.get("/chat/{demo_id}")
@limiter.limit("30/minute")  # Public endpoint for viewing demo chats
async def get_demo_chat(
    request: Request,
    demo_id: str,
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get demo chat data for viewing.

    This endpoint returns the encrypted chat data along with the encryption key,
    allowing non-authenticated users to view the demo chat.

    This is public but rate-limited to prevent abuse.
    """
    try:
        # 1. Try to get from cache first
        cached_data = await directus_service.cache.get_demo_chat_data(demo_id)
        if cached_data:
            logger.debug(f"Cache HIT: Returning demo chat data for {demo_id}")
            return cached_data

        # 2. Get demo chat metadata
        demo_chat = await directus_service.demo_chat.get_demo_chat_by_id(demo_id)

        if not demo_chat:
            logger.debug(f"Demo chat {demo_id} not found")
            raise HTTPException(status_code=404, detail="Demo chat not found")

        if not demo_chat.get("approved_by_admin", False):
            logger.debug(f"Demo chat {demo_id} not approved by admin")
            raise HTTPException(status_code=404, detail="Demo chat not found")

        # Get the original chat data using the stored chat_id
        original_chat_id = demo_chat.get("original_chat_id")
        if not original_chat_id:
            logger.error(f"Demo chat {demo_id} missing original_chat_id")
            raise HTTPException(status_code=500, detail="Demo chat configuration error")

        # Fetch the shared chat data (this will be encrypted)
        # We use the existing share endpoint logic but bypass the dummy data
        original_chat = await directus_service.chat.get_chat_metadata(original_chat_id)

        if not original_chat or original_chat.get("is_private", True):
            logger.error(f"Original chat {original_chat_id} for demo {demo_id} is not available")
            raise HTTPException(status_code=404, detail="Demo chat content not available")

        # Get messages for the chat
        messages = await directus_service.chat.get_all_messages_for_chat(
            chat_id=original_chat_id,
            decrypt_content=False  # Return encrypted messages
        )

        # Get embeds for the chat
        hashed_chat_id = hashlib.sha256(original_chat_id.encode()).hexdigest()
        embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
        embed_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_id(hashed_chat_id, include_master_keys=False)

        # Return the demo chat data including the encryption key
        response_data = {
            "demo_id": demo_id,
            "title": demo_chat.get("title"),
            "summary": demo_chat.get("summary"),
            "category": demo_chat.get("category"),
            "chat_data": {
                "chat_id": original_chat_id,
                "encryption_key": demo_chat.get("encrypted_key"),  # Provide the key for decryption
                "encrypted_title": original_chat.get("encrypted_title"),
                "encrypted_chat_summary": original_chat.get("encrypted_chat_summary"),
                "encrypted_follow_up_request_suggestions": original_chat.get("encrypted_follow_up_request_suggestions"),
                "encrypted_icon": original_chat.get("encrypted_icon"),
                "encrypted_category": original_chat.get("encrypted_category"),
                "messages": messages or [],
                "embeds": embeds or [],
                "embed_keys": embed_keys or []
            }
        }

        # Cache the response data
        await directus_service.cache.set_demo_chat_data(demo_id, response_data)

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching demo chat {demo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch demo chat")

@router.delete("/chat/{demo_id}")
@limiter.limit("10/hour")  # Strict rate limit for deletion
async def deactivate_demo_chat(
    request: Request,
    demo_id: str,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Deactivate (soft delete) a demo chat.

    Requires admin authentication.
    """
    try:
        # TODO: Add admin role check here

        success = await directus_service.demo_chat.deactivate_demo_chat(demo_id)

        if not success:
            raise HTTPException(status_code=404, detail="Demo chat not found")

        logger.info(f"Deactivated demo chat {demo_id} by user {current_user.id}")

        return {
            "success": True,
            "demo_id": demo_id,
            "message": "Demo chat deactivated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating demo chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to deactivate demo chat")