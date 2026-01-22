# backend/core/api/app/routes/demo_chat.py
"""
REST API endpoints for demo chat functionality.
Handles creation, approval, and public access to demo chats.
"""

import logging
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
    lang: str = Query("en", description="Language code"),
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get list of approved and published demo chats.
    """
    try:
        # 1. Try to get from cache first
        cached_data = await directus_service.cache.get_demo_chats_list(lang, category=category)
        if cached_data:
            logger.debug(f"Cache HIT: Returning demo chats list for {lang} (category: {category})")
            return cached_data

        # 2. Get from database
        params = {
            "filter": {
                "status": {"_eq": "published"},
                "is_active": {"_eq": True}
            },
            "sort": ["-created_at"]
        }
        if category:
            params["filter"]["category"] = {"_eq": category}

        demo_chats = await directus_service.get_items("demo_chats", params)
        
        public_demo_chats = []
        for demo in demo_chats:
            # Get translation
            translation = await directus_service.demo_chat.get_demo_chat_translation(demo["demo_id"], lang)
            # Fallback to English if translation not found
            if not translation and lang != "en":
                translation = await directus_service.demo_chat.get_demo_chat_translation(demo["demo_id"], "en")
            
            if translation:
                public_demo_chats.append({
                    "demo_id": demo["demo_id"],
                    "title": translation.get("title"),
                    "summary": translation.get("summary"),
                    "category": demo.get("category"),
                    "created_at": demo.get("created_at"),
                    "status": demo.get("status")
                })

        response_data = {
            "demo_chats": public_demo_chats,
            "count": len(public_demo_chats)
        }

        # 3. Cache the result
        await directus_service.cache.set_demo_chats_list(lang, response_data, category=category)

        return response_data

    except Exception as e:
        logger.error(f"Error fetching demo chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch demo chats")

@router.get("/chat/{demo_id}")
@limiter.limit("30/minute")  # Public endpoint for viewing demo chats
async def get_demo_chat(
    request: Request,
    demo_id: str,
    lang: str = Query("en", description="Language code"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get full demo chat data for viewing.
    """
    try:
        # 1. Try to get from cache first
        cached_data = await directus_service.cache.get_demo_chat_data(demo_id, lang)
        if cached_data:
            logger.debug(f"Cache HIT: Returning demo chat data for {demo_id} ({lang})")
            return cached_data

        # 2. Get demo chat metadata
        demo_chat = await directus_service.demo_chat.get_demo_chat_by_id(demo_id)
        if not demo_chat or demo_chat.get("status") != "published":
            raise HTTPException(status_code=404, detail="Demo chat not found or not yet published")

        # 3. Get translation
        translation = await directus_service.demo_chat.get_demo_chat_translation(demo_id, lang)
        if not translation and lang != "en":
            translation = await directus_service.demo_chat.get_demo_chat_translation(demo_id, "en")
        
        if not translation:
            raise HTTPException(status_code=404, detail="Translation not found")

        # 4. Get messages and embeds
        messages = await directus_service.demo_chat.get_demo_messages(demo_id, lang)
        if not messages and lang != "en":
            messages = await directus_service.demo_chat.get_demo_messages(demo_id, "en")
            
        embeds = await directus_service.demo_chat.get_demo_embeds(demo_id, lang)
        if not embeds and lang != "en":
            embeds = await directus_service.demo_chat.get_demo_embeds(demo_id, "en")

        # 5. Decrypt content for client (No client-side decryption needed for demos)
        from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
        encryption_service = request.app.state.encryption_service
        
        decrypted_messages = []
        for msg in (messages or []):
            decrypted_content = await encryption_service.decrypt(
                msg.get("encrypted_content", ""), 
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            decrypted_messages.append({
                "message_id": str(msg.get("id")),
                "role": msg.get("role"),
                "content": decrypted_content,
                "created_at": msg.get("created_at")
            })

        decrypted_embeds = []
        for emb in (embeds or []):
            decrypted_content = await encryption_service.decrypt(
                emb.get("encrypted_content", ""), 
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            decrypted_embeds.append({
                "embed_id": emb.get("embed_id"),
                "type": emb.get("type"),
                "content": decrypted_content,
                "created_at": emb.get("created_at")
            })

        # 6. Prepare response
        response_data = {
            "demo_id": demo_id,
            "title": translation.get("title"),
            "summary": translation.get("summary"),
            "category": demo_chat.get("category"),
            "follow_up_suggestions": translation.get("follow_up_suggestions"),
            "chat_data": {
                "chat_id": demo_chat.get("original_chat_id"),
                "messages": decrypted_messages,
                "embeds": decrypted_embeds,
                "encryption_mode": "none" # Cleartext for client
            }
        }

        # 7. Cache the response data
        await directus_service.cache.set_demo_chat_data(demo_id, lang, response_data)

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
        # Check if user is admin
        # TODO: Implement proper admin check dependency
        
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
