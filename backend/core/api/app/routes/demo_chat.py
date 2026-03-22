# backend/core/api/app/routes/demo_chat.py
"""
REST API endpoints for demo chat functionality.
Handles creation, approval, and public access to demo chats.

ARCHITECTURE — Slug-based IDs:
  Each demo chat has a stable 'slug' field stored in Directus (e.g. 'demo-planning-a-trip').
  The slug is used as the chat_id on the frontend and as the URL path for SEO pages.
  The old positional demo-1/demo-2 system has been replaced — slugs are now the canonical ID.

  Lookup priority for GET /chat/{identifier}:
    1. Slug field match  (e.g. 'demo-planning-a-trip')
    2. UUID match        (raw Directus UUID, for internal/admin use)

  Slugs must:
    - Start with 'demo-' (so isPublicChat() works on the frontend)
    - Be URL-safe lowercase strings with hyphens
    - Be unique across all demo chats
"""

import re
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

# --- Helpers ---

def slugify(text: str) -> str:
    """
    Convert a title string to a URL-safe slug with 'demo-' prefix.
    Example: 'Planning a Trip to Japan' -> 'demo-planning-a-trip-to-japan'
    """
    text = text.lower().strip()
    # Replace spaces and non-alphanumeric chars (except hyphens) with hyphens
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    return f"demo-{text}"


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
    category: Optional[str] = Query(None, description="Filter by demo_chat_category"),
    hashes: Optional[str] = Query(None, description="Comma-separated slug:hash pairs for change detection"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get list of approved and published demo chats.

    Each demo chat is identified by its stable 'slug' field (e.g. 'demo-planning-a-trip').
    The slug is returned as both 'demo_id' (for backwards compat) and 'slug' fields.

    Supports change detection via the 'hashes' parameter:
    - Format: "demo-planning:abc123,demo-travel:def456" (slug:content_hash pairs)
    - Returns an 'updated' flag per demo indicating whether content changed
    """
    try:
        # Parse client hashes for change detection (keyed by slug)
        client_hashes: Dict[str, str] = {}
        if hashes:
            for pair in hashes.split(","):
                if ":" in pair:
                    slug, hash_value = pair.split(":", 1)
                    client_hashes[slug.strip()] = hash_value.strip()

        # 1. Try to get from cache first (only if not doing hash comparison)
        if not client_hashes:
            cached_data = await directus_service.cache.get_demo_chats_list(lang, category=category)
            if cached_data:
                logger.debug(f"Cache HIT: Returning demo chats list for {lang} (category: {category})")
                return cached_data

        # 2. Get from database
        params: Dict[str, Any] = {
            "filter": {
                "status": {"_eq": "published"},
                "is_active": {"_eq": True}
            },
            "sort": ["-created_at"]
        }
        if category:
            params["filter"]["demo_chat_category"] = {"_eq": category}

        demo_chats = await directus_service.get_items("demo_chats", params)

        public_demo_chats = []

        for idx, demo in enumerate(demo_chats):
            demo_uuid = demo["id"]
            content_hash = demo.get("content_hash", "")

            # Use the stored slug as the stable ID.
            # Fall back to auto-generating from title if slug is not yet set
            # (handles existing records that pre-date the slug field).
            stored_slug = demo.get("slug") or ""
            if not stored_slug:
                # Auto-generate from the original title field as a fallback.
                # This ensures old records still work during the migration period.
                fallback_title = demo.get("title") or f"demo-chat-{idx + 1}"
                stored_slug = slugify(fallback_title)
                logger.debug(f"Demo {demo_uuid} has no slug — using generated fallback: {stored_slug}")

            demo_category = demo.get("category")
            demo_icon = demo.get("icon")
            demo_chat_category = demo.get("demo_chat_category", "for_everyone")

            # Get translation by UUID
            translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_uuid, lang)
            # Fallback to English if translation not found
            if not translation and lang != "en":
                translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_uuid, "en")

            if translation:
                title = translation.get("title")
                summary = translation.get("summary")

                demo_data: Dict[str, Any] = {
                    # 'demo_id' kept for backwards compatibility with existing frontend code
                    # that reads demo_id from the list response. Now equals the slug.
                    "demo_id": stored_slug,
                    "slug": stored_slug,
                    "uuid": demo_uuid,
                    "title": title or "Demo Chat",
                    "summary": summary,
                    "category": demo_category,
                    "icon": demo_icon,
                    "demo_chat_category": demo_chat_category,
                    "content_hash": content_hash,
                    "created_at": demo.get("created_at"),
                    "updated_at": demo.get("updated_at"),
                    "status": demo.get("status")
                }

                # Add 'updated' flag if client provided hashes for change detection
                if client_hashes:
                    client_hash = client_hashes.get(stored_slug, "")
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


@router.get("/chat/{identifier}")
@limiter.limit("30/minute")  # Public endpoint for viewing demo chats
async def get_demo_chat(
    request: Request,
    identifier: str,
    lang: str = Query("en", description="Language code"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get full demo chat data for viewing.

    Accepts:
      - Slug identifiers (e.g. 'demo-planning-a-trip-to-japan') — preferred, stable
      - Raw UUIDs — for internal/admin use

    The old positional demo-1/demo-2 format is no longer supported.
    """
    try:
        # 1. Try to get from cache first
        cached_data = await directus_service.cache.get_demo_chat_data(identifier, lang)
        if cached_data:
            logger.debug(f"Cache HIT: Returning demo chat data for {identifier} ({lang})")
            return cached_data

        # 2. Resolve identifier → UUID
        # Lookup order: slug field → UUID (raw Directus UUID)
        demo_chat_uuid: Optional[str] = None
        resolved_slug: Optional[str] = None

        # Try slug lookup first (most common case for production traffic)
        slug_results = await directus_service.get_items("demo_chats", {
            "filter": {
                "slug": {"_eq": identifier},
                "is_active": {"_eq": True}
            },
            "limit": 1
        })
        if slug_results:
            demo_chat_uuid = slug_results[0]["id"]
            resolved_slug = identifier
            logger.debug(f"Resolved '{identifier}' via slug field → UUID {demo_chat_uuid}")
        else:
            # Fall back to UUID lookup (handles admin/internal usage)
            # A UUID looks like: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            uuid_pattern = re.compile(
                r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
                re.IGNORECASE
            )
            if uuid_pattern.match(identifier):
                demo_chat_uuid = identifier
                logger.debug(f"Treating '{identifier}' as raw UUID")
            else:
                logger.warning(f"Could not resolve demo chat identifier: '{identifier}' (not a slug or UUID)")
                raise HTTPException(status_code=404, detail="Demo chat not found")

        # 3. Fetch the full demo chat record by UUID
        demo_chats = await directus_service.get_items("demo_chats", {
            "filter": {"id": {"_eq": demo_chat_uuid}},
            "limit": 1
        })
        demo_chat = demo_chats[0] if demo_chats else None

        if not demo_chat or demo_chat.get("status") != "published":
            logger.warning(
                f"Demo chat {demo_chat_uuid} not found or not published "
                f"(found={demo_chat is not None}, status={demo_chat.get('status') if demo_chat else 'None'})"
            )
            raise HTTPException(status_code=404, detail="Demo chat not found or not yet published")

        # Determine the canonical slug for this demo chat
        canonical_slug = demo_chat.get("slug") or resolved_slug or identifier

        # 4. Get translation
        translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_chat_uuid, lang)
        if not translation and lang != "en":
            translation = await directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_chat_uuid, "en")

        if not translation:
            logger.error(f"No translation found for demo chat {demo_chat_uuid} (lang={lang})")
            raise HTTPException(status_code=404, detail="Translation not found")

        title = translation.get("title")
        summary = translation.get("summary")
        follow_up_suggestions = []

        if translation.get("follow_up_suggestions"):
            try:
                import json
                follow_up_suggestions = json.loads(translation["follow_up_suggestions"])
            except Exception as e:
                logger.warning(f"Failed to parse follow-up suggestions: {e}")

        category = demo_chat.get("category")
        icon = demo_chat.get("icon")
        demo_chat_category = demo_chat.get("demo_chat_category", "for_everyone")

        # 5. Get messages and embeds
        messages = await directus_service.demo_chat.get_demo_messages_by_uuid(demo_chat_uuid, lang)
        if not messages and lang != "en":
            messages = await directus_service.demo_chat.get_demo_messages_by_uuid(demo_chat_uuid, "en")

        embeds = await directus_service.demo_chat.get_demo_embeds_by_uuid(demo_chat_uuid, lang)
        if not embeds and lang != "en":
            embeds = await directus_service.demo_chat.get_demo_embeds_by_uuid(demo_chat_uuid, "en")

        # 6. Build cleartext message list
        import json as json_module

        decrypted_messages = []
        for msg in (messages or []):
            content = msg.get("content", "")

            # PRIVACY: Strip user_message_id from system message content.
            # The user_message_id references the original chat's message ID which:
            # 1. Leaks metadata from the original conversation
            # 2. Doesn't match any message ID in the demo chat (IDs are regenerated)
            if msg.get("role") == "system" and content:
                try:
                    parsed_content = json_module.loads(content)
                    if isinstance(parsed_content, dict) and "user_message_id" in parsed_content:
                        del parsed_content["user_message_id"]
                        content = json_module.dumps(parsed_content)
                        logger.debug("Stripped user_message_id from system message for privacy")
                except (json_module.JSONDecodeError, TypeError):
                    pass

            decrypted_messages.append({
                "message_id": str(msg.get("id")),
                "role": msg.get("role"),
                "content": content,
                "category": msg.get("category"),
                "model_name": msg.get("model_name"),
                "created_at": msg.get("original_created_at")
            })

        decrypted_embeds = []
        for emb in (embeds or []):
            decrypted_embeds.append({
                "embed_id": emb.get("original_embed_id"),
                "type": emb.get("type"),
                "content": emb.get("content", ""),
                "created_at": emb.get("original_created_at")
            })

        # 7. Build response
        # ARCHITECTURE: The slug is used as chat_id so isPublicChat() works on the frontend.
        # All chat_id values start with 'demo-' (e.g. 'demo-planning-a-trip').
        response_data = {
            "demo_id": canonical_slug,   # Backwards compat — equals slug
            "slug": canonical_slug,       # Stable URL-friendly identifier
            "uuid": demo_chat_uuid,
            "title": title,
            "summary": summary,
            "category": category,
            "icon": icon,
            "demo_chat_category": demo_chat_category,
            "content_hash": demo_chat.get("content_hash", ""),
            "follow_up_suggestions": follow_up_suggestions,
            "updated_at": demo_chat.get("updated_at"),
            "created_at": demo_chat.get("created_at"),
            "chat_data": {
                # chat_id = slug so the frontend can use it as a stable key
                # and isPublicChat() continues to work (starts with 'demo-')
                "chat_id": canonical_slug,
                "messages": decrypted_messages,
                "embeds": decrypted_embeds,
                "encryption_mode": "none"
            }
        }

        # 8. Cache the response
        await directus_service.cache.set_demo_chat_data(identifier, lang, response_data)

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching demo chat {identifier}: {e}", exc_info=True)
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
    Permanently delete a demo chat and all related data.

    CRITICAL: This performs a HARD delete of:
    - The demo_chat entry
    - All demo_messages (all languages)
    - All demo_embeds (all languages)
    - All demo_chat_translations (all languages)

    Requires admin authentication.
    """
    try:
        success = await directus_service.demo_chat.deactivate_demo_chat(demo_id)

        if not success:
            raise HTTPException(status_code=404, detail="Demo chat not found")

        logger.info(f"Deleted demo chat {demo_id} and all related data by user {current_user.id}")

        return {
            "success": True,
            "demo_id": demo_id,
            "message": "Demo chat and all related data deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating demo chat {demo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to deactivate demo chat")
