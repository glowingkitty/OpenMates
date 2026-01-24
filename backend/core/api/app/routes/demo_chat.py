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
    hashes: Optional[str] = Query(None, description="Comma-separated list of demo_id:hash pairs for change detection"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get list of approved and published demo chats.
    
    Supports change detection via the `hashes` parameter:
    - If provided, returns a list of demos with an `updated` flag indicating if content changed
    - Format: "demo-1:abc123,demo-2:def456" (demo_id:content_hash pairs)
    - This allows clients to only fetch full data for changed demos
    """
    try:
        # Parse client hashes for change detection
        client_hashes: Dict[str, str] = {}
        if hashes:
            for pair in hashes.split(","):
                if ":" in pair:
                    demo_id, hash_value = pair.split(":", 1)
                    client_hashes[demo_id.strip()] = hash_value.strip()
        
        # 1. Try to get from cache first (only if not doing hash comparison)
        if not client_hashes:
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
        encryption_service = request.app.state.encryption_service
        from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
        
        for idx, demo in enumerate(demo_chats):
            # Use UUID as the ID instead of demo_id
            demo_uuid = demo["id"]
            content_hash = demo.get("content_hash", "")
            
            # Generate client-side display ID based on order (demo-1, demo-2, etc.)
            # The frontend will use this for display/routing
            display_id = f"demo-{idx + 1}"
            
            # Decrypt category if present
            category = None
            if demo.get("encrypted_category"):
                try:
                    category = await encryption_service.decrypt(
                        demo["encrypted_category"],
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt category for demo {demo_uuid}: {e}")
            
            # Get translation by UUID
            translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_uuid, lang)
            # Fallback to English if translation not found
            if not translation and lang != "en":
                translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_uuid, "en")
            
            if translation:
                # Decrypt translated fields
                title = None
                summary = None
                if translation.get("encrypted_title"):
                    try:
                        title = await encryption_service.decrypt(
                            translation["encrypted_title"],
                            key_name=DEMO_CHATS_ENCRYPTION_KEY
                        )
                    except Exception as e:
                        logger.warning(f"Failed to decrypt title for demo {demo_uuid}: {e}")
                
                if translation.get("encrypted_summary"):
                    try:
                        summary = await encryption_service.decrypt(
                            translation["encrypted_summary"],
                            key_name=DEMO_CHATS_ENCRYPTION_KEY
                        )
                    except Exception as e:
                        logger.warning(f"Failed to decrypt summary for demo {demo_uuid}: {e}")
                
                demo_data = {
                    "demo_id": display_id,  # Client-side display ID
                    "uuid": demo_uuid,  # Server UUID for lookups
                    "title": title or "Demo Chat",
                    "summary": summary,
                    "category": category,
                    "content_hash": content_hash,
                    "created_at": demo.get("created_at"),
                    "status": demo.get("status")
                }
                
                # Add `updated` flag if client provided hashes for change detection
                if client_hashes:
                    client_hash = client_hashes.get(display_id, "")
                    demo_data["updated"] = (content_hash != client_hash) if content_hash else True
                
                public_demo_chats.append(demo_data)

        response_data = {
            "demo_chats": public_demo_chats,
            "count": len(public_demo_chats)
        }

        # 3. Cache the result (only if not doing hash comparison)
        if not client_hashes:
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
    Accepts display IDs (demo-1, demo-2) or UUIDs.
    """
    try:
        # 1. Try to get from cache first
        cached_data = await directus_service.cache.get_demo_chat_data(demo_id, lang)
        if cached_data:
            logger.debug(f"Cache HIT: Returning demo chat data for {demo_id} ({lang})")
            return cached_data

        # 2. Get demo chat metadata - need to map display ID to UUID
        demo_chat_uuid = None
        
        # Check if demo_id is a display ID (demo-1, demo-2, etc.) or UUID
        if demo_id.startswith("demo-"):
            # It's a display ID - need to fetch all demos and find the matching one by order
            try:
                index = int(demo_id.split("-")[1]) - 1  # demo-1 -> index 0

                # Get published demos sorted by creation (same as list endpoint)
                params = {
                    "filter": {
                        "status": {"_eq": "published"},
                        "is_active": {"_eq": True}
                    },
                    "sort": ["-created_at"]
                }
                demos = await directus_service.get_items("demo_chats", params)

                logger.info(f"Found {len(demos)} published demo chats for display ID {demo_id}, looking for index {index}")

                if demos and len(demos) > index:
                    demo_chat_uuid = demos[index]["id"]
                    logger.info(f"Mapped display ID {demo_id} to UUID {demo_chat_uuid}")
                else:
                    logger.error(f"No demo chat found at index {index} for display ID {demo_id}")
                    raise HTTPException(status_code=404, detail="Demo chat not found")
            except (ValueError, IndexError) as e:
                logger.error(f"Invalid demo ID format {demo_id}: {e}")
                raise HTTPException(status_code=404, detail="Invalid demo ID format")
        else:
            # Assume it's a UUID
            demo_chat_uuid = demo_id

        # Fetch the demo chat by UUID
        logger.info(f"Fetching demo chat by UUID: {demo_chat_uuid}")
        demo_chats = await directus_service.get_items("demo_chats", {
            "filter": {"id": {"_eq": demo_chat_uuid}},
            "limit": 1
        })
        demo_chat = demo_chats[0] if demo_chats else None
        logger.info(f"Demo chat found: {demo_chat is not None}, status: {demo_chat.get('status') if demo_chat else 'None'}")

        if not demo_chat or demo_chat.get("status") != "published":
            logger.error(f"Demo chat not found or not published: demo_chat={demo_chat is not None}, status={demo_chat.get('status') if demo_chat else 'None'}")
            raise HTTPException(status_code=404, detail="Demo chat not found or not yet published")

        # 3. Get translation by UUID
        logger.info(f"Looking for translation for demo_chat_uuid {demo_chat_uuid} in language {lang}")
        translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_chat_uuid, lang)
        logger.info(f"Translation for {lang}: {translation is not None}")

        if not translation and lang != "en":
            logger.info(f"No translation for {lang}, trying English")
            translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_chat_uuid, "en")
            logger.info(f"English translation: {translation is not None}")

        if not translation:
            logger.error(f"No translation found for demo chat {demo_chat_uuid}")
            raise HTTPException(status_code=404, detail="Translation not found")
        
        # Decrypt translation metadata
        encryption_service = request.app.state.encryption_service
        from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
        
        title = None
        summary = None
        follow_up_suggestions = []
        
        if translation.get("encrypted_title"):
            try:
                title = await encryption_service.decrypt(
                    translation["encrypted_title"],
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt title: {e}")
        
        if translation.get("encrypted_summary"):
            try:
                summary = await encryption_service.decrypt(
                    translation["encrypted_summary"],
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt summary: {e}")
        
        if translation.get("encrypted_follow_up_suggestions"):
            try:
                import json
                decrypted_followup = await encryption_service.decrypt(
                    translation["encrypted_follow_up_suggestions"],
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                if decrypted_followup:
                    follow_up_suggestions = json.loads(decrypted_followup)
            except Exception as e:
                logger.warning(f"Failed to decrypt follow-up suggestions: {e}")
        
        # Decrypt category and icon from demo_chat
        category = None
        icon = None
        
        if demo_chat.get("encrypted_category"):
            try:
                category = await encryption_service.decrypt(
                    demo_chat["encrypted_category"],
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt category: {e}")
        
        if demo_chat.get("encrypted_icon"):
            try:
                icon = await encryption_service.decrypt(
                    demo_chat["encrypted_icon"],
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt icon: {e}")

        # 4. Get messages and embeds by UUID
        messages = await directus_service.demo_chat.get_demo_messages_by_uuid(demo_chat_uuid, lang)
        if not messages and lang != "en":
            messages = await directus_service.demo_chat.get_demo_messages_by_uuid(demo_chat_uuid, "en")
            
        embeds = await directus_service.demo_chat.get_demo_embeds_by_uuid(demo_chat_uuid, lang)
        if not embeds and lang != "en":
            embeds = await directus_service.demo_chat.get_demo_embeds_by_uuid(demo_chat_uuid, "en")

        # 5. Decrypt content for client (No client-side decryption needed for demos)
        from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
        encryption_service = request.app.state.encryption_service
        
        decrypted_messages = []
        for msg in (messages or []):
            decrypted_content = await encryption_service.decrypt(
                msg.get("encrypted_content", ""), 
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            
            decrypted_category = None
            if msg.get("encrypted_category"):
                try:
                    decrypted_category = await encryption_service.decrypt(
                        msg["encrypted_category"],
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt message category: {e}")

            decrypted_model_name = None
            if msg.get("encrypted_model_name"):
                try:
                    decrypted_model_name = await encryption_service.decrypt(
                        msg["encrypted_model_name"],
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt message model name: {e}")

            decrypted_messages.append({
                "message_id": str(msg.get("id")),
                "role": msg.get("role"),
                "content": decrypted_content,
                "category": decrypted_category, # Return cleartext category
                "model_name": decrypted_model_name, # Return cleartext model name
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
        # ARCHITECTURE: Demo chats use demo_id (e.g., "demo-1") as their chat_id
        # Messages are already server-side decrypted, so no encryption_key is needed
        # content_hash is included for client-side change detection
        response_data = {
            "demo_id": demo_id,
            "title": title,
            "summary": summary,
            "category": category,
            "icon": icon,
            "content_hash": demo_chat.get("content_hash", ""),
            "follow_up_suggestions": follow_up_suggestions,
            "chat_data": {
                "chat_id": demo_id,  # Use demo_id as the chat identifier (not original_chat_id)
                "messages": decrypted_messages,  # Already decrypted server-side (cleartext)
                "embeds": decrypted_embeds,  # Already decrypted server-side (cleartext)
                "encryption_mode": "none"  # Cleartext - no client-side decryption needed
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
