# backend/core/api/app/routes/share.py
#
# REST API endpoints for share chat functionality
# Handles public access to shared chats and OG metadata updates

import logging
import hashlib
import re
import time
import os
from typing import Dict, Any, Optional, List, Literal
from fastapi import APIRouter, HTTPException, Request, Depends, Query, Response
from pydantic import BaseModel, Field

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services import cache_config
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/share",
    tags=["Share"]
)

# --- Dependency to get services from app.state ---

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service

def get_encryption_service(request: Request) -> EncryptionService:
    if not hasattr(request.app.state, 'encryption_service'):
        logger.error("EncryptionService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.encryption_service

def get_cache_service(request: Request) -> CacheService:
    if not hasattr(request.app.state, 'cache_service'):
        logger.error("CacheService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.cache_service

# --- Request/Response Models ---

class ShareChatMetadataUpdate(BaseModel):
    """Request model for updating OG metadata when sharing a chat"""
    chat_id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    follow_up_suggestions: Optional[List[str]] = None
    is_shared: Optional[bool] = None  # Whether the chat is being shared (set to true when share link is created)
    share_pii: Optional[bool] = None  # Whether shared chat viewers may receive encrypted PII mappings
    share_highlights: Optional[bool] = None  # Whether shared chat viewers may receive encrypted highlights/comments
    share_with_community: Optional[bool] = None  # Whether to email the share link to admin for community consideration
    share_link: Optional[str] = None  # Full share link with encryption key (for community sharing email)
    encrypted_shared_short_url: Optional[str] = None  # Client-encrypted /s/<token>#<shortKey> for owner share UI reuse

class UnshareChatRequest(BaseModel):
    """Request model for unsharing a chat"""
    chat_id: str

# --- Helper Functions ---

def generate_dummy_encrypted_data(chat_id: str) -> Dict[str, Any]:
    """
    Generate deterministic dummy encrypted data for a chat ID.
    This prevents enumeration attacks by making non-existent chats look like real ones.
    
    The dummy data is deterministic based on the chat_id, so the same chat_id
    always returns the same dummy data (consistent for OG tag caching).
    """
    # Use chat_id as seed for deterministic dummy data
    seed = hashlib.sha256(chat_id.encode()).digest()
    
    # Generate deterministic "encrypted" data (base64 encoded random-looking bytes)
    import base64
    dummy_title = base64.b64encode(seed[:16]).decode('utf-8')
    dummy_summary = base64.b64encode(seed[16:32]).decode('utf-8')
    
    # Generate deterministic dummy messages (2-3 messages)
    dummy_messages = []
    for i in range(2):
        message_seed = hashlib.sha256((chat_id + str(i)).encode()).digest()
        dummy_messages.append({
            "message_id": f"dummy-{base64.b64encode(message_seed[:8]).decode('utf-8')}",
            "encrypted_content": base64.b64encode(message_seed[:32]).decode('utf-8'),
            "sender": "user" if i == 0 else "assistant",
            "timestamp": int(time.time()) - (2 - i) * 60
        })
    
    return {
        "chat_id": chat_id,
        "encrypted_title": dummy_title,
        "encrypted_chat_summary": dummy_summary,
        "messages": dummy_messages,
        "is_dummy": True  # Internal flag, not sent to client
    }

async def get_shared_chat_or_dummy(chat_id: str, directus_service: DirectusService) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not chat or chat.get("is_private", False):
        dummy_data = generate_dummy_encrypted_data(chat_id)
        dummy_data.pop("is_dummy", None)
        return None, dummy_data
    return chat, None

def sanitize_shared_pii(messages: List[Any], share_pii: bool) -> List[Any]:
    if share_pii or not messages:
        return messages
    import json
    sanitized_messages = []
    for message in messages:
        if isinstance(message, str):
            try:
                parsed_message = json.loads(message)
                if isinstance(parsed_message, dict):
                    parsed_message.pop("encrypted_pii_mappings", None)
                    sanitized_messages.append(json.dumps(parsed_message))
                else:
                    sanitized_messages.append(message)
            except Exception:
                sanitized_messages.append(message)
            continue
        sanitized = dict(message)
        sanitized.pop("encrypted_pii_mappings", None)
        sanitized_messages.append(sanitized)
    return sanitized_messages

async def get_shared_chat_auxiliary_payload(
    chat_id: str,
    chat: Dict[str, Any],
    directus_service: DirectusService,
) -> Dict[str, Any]:
    import hashlib
    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    share_highlights = chat.get("share_highlights", True)
    if share_highlights is None:
        share_highlights = True

    embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
    embed_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_id(hashed_chat_id, include_master_keys=False)
    message_highlights = []
    if share_highlights:
        message_highlights = await directus_service.get_items(
            "message_highlights",
            params={
                "filter[chat_id][_eq]": chat_id,
                "fields": "id,chat_id,message_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
                "sort": "created_at",
                "limit": -1,
            },
            admin_required=True,
        ) or []
    code_run_outputs = await directus_service.get_items(
        "code_run_outputs",
        params={
            "filter[chat_id][_eq]": chat_id,
            "fields": "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
            "sort": "-updated_at",
            "limit": -1,
        },
        admin_required=True,
    ) or []
    sub_chats = await directus_service.get_items(
        "chats",
        params={
            "filter[parent_id][_eq]": chat_id,
            "fields": "id,encrypted_title,created_at,updated_at,messages_v,title_v,last_edited_overall_timestamp,unread_count,encrypted_chat_summary,encrypted_icon,encrypted_category,parent_id,is_sub_chat,budget_limit,budget_spent",
            "sort": "created_at",
            "limit": -1,
        },
        admin_required=True,
    ) or []
    return {
        "embeds": embeds or [],
        "embed_keys": embed_keys or [],
        "sub_chats": sub_chats,
        "code_run_outputs": code_run_outputs,
        "message_highlights": message_highlights,
        "share_highlights": bool(share_highlights),
    }

def shared_chat_metadata_payload(chat_id: str, chat: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "chat_id": chat_id,
        "encrypted_title": chat.get("encrypted_title"),
        "encrypted_chat_summary": chat.get("encrypted_chat_summary"),
        "encrypted_follow_up_request_suggestions": chat.get("encrypted_follow_up_request_suggestions"),
        "encrypted_icon": chat.get("encrypted_icon"),
        "encrypted_category": chat.get("encrypted_category"),
        "share_pii": bool(chat.get("share_pii", False)),
        "is_dummy": False,
    }

# --- Endpoints ---

@router.get("/chat/{chat_id}")
@limiter.limit("30/minute")  # Prevent brute force attacks on chat IDs
async def get_shared_chat(
    request: Request,
    chat_id: str,
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get encrypted chat data for a shared chat.
    
    Returns:
    - Real encrypted data if chat exists and is_private = false
    - Dummy encrypted data if chat doesn't exist or is_private = true
      (prevents enumeration attacks)
    
    Security:
    - Rate limited to prevent brute force attacks
    - Returns consistent dummy data for non-existent chats
    - Only returns real data if is_private = false
    """
    try:
        # Fetch chat from database
        chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
        
        if not chat:
            # Chat doesn't exist - return dummy data to prevent enumeration
            logger.debug(f"Chat {chat_id} not found, returning dummy data")
            dummy_data = generate_dummy_encrypted_data(chat_id)
            # Remove internal flag before returning
            dummy_data.pop("is_dummy", None)
            return dummy_data
        
        # Check if chat is private (unshared)
        is_private = chat.get("is_private", False)
        if is_private:
            # Chat was unshared - return dummy data
            logger.debug(f"Chat {chat_id} is private (unshared), returning dummy data")
            dummy_data = generate_dummy_encrypted_data(chat_id)
            dummy_data.pop("is_dummy", None)
            return dummy_data
        
        share_pii = bool(chat.get("share_pii", False))
        share_highlights = chat.get("share_highlights", True)
        if share_highlights is None:
            share_highlights = True

        # Chat exists and is shared - return real encrypted data
        # Note: We return encrypted data as-is (client-side decryption)
        # The encryption key is in the URL fragment, never sent to server
        logger.debug(f"Returning real encrypted data for shared chat {chat_id}")
        
        # Get messages for the chat (encrypted, as stored in database)
        messages = await directus_service.chat.get_all_messages_for_chat(
            chat_id=chat_id,
            decrypt_content=False  # Return encrypted messages
        )
        if not share_pii and messages:
            import json
            sanitized_messages = []
            for message in messages:
                if isinstance(message, str):
                    try:
                        parsed_message = json.loads(message)
                        if isinstance(parsed_message, dict):
                            parsed_message.pop("encrypted_pii_mappings", None)
                            sanitized_messages.append(json.dumps(parsed_message))
                        else:
                            sanitized_messages.append(message)
                    except Exception:
                        sanitized_messages.append(message)
                    continue
                sanitized = dict(message)
                sanitized.pop("encrypted_pii_mappings", None)
                sanitized_messages.append(sanitized)
            messages = sanitized_messages
        
        # Get embeds for the chat (encrypted, as stored in database)
        import hashlib
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        embeds = await directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
        
        # Get embed_keys for this chat (wrapped key architecture)
        # These contain AES(embed_key, chat_key) entries that allow shared chat recipients
        # to unwrap embed_keys using the chat_encryption_key from the share link
        # NOTE: For share links, we only need chat key entries (not master keys) since
        # share recipients don't have access to the owner's master key
        embed_keys = await directus_service.embed.get_embed_keys_by_hashed_chat_id(hashed_chat_id, include_master_keys=False)

        message_highlights = []
        if share_highlights:
            message_highlights = await directus_service.get_items(
                "message_highlights",
                params={
                    "filter[chat_id][_eq]": chat_id,
                    "fields": "id,chat_id,message_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
                    "sort": "created_at",
                    "limit": -1,
                },
                admin_required=True,
            ) or []

        code_run_outputs = await directus_service.get_items(
            "code_run_outputs",
            params={
                "filter[chat_id][_eq]": chat_id,
                "fields": "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
                "sort": "-updated_at",
                "limit": -1,
            },
            admin_required=True,
        ) or []

        sub_chats = await directus_service.get_items(
            "chats",
            params={
                "filter[parent_id][_eq]": chat_id,
                "fields": "id,encrypted_title,created_at,updated_at,messages_v,title_v,last_edited_overall_timestamp,unread_count,encrypted_chat_summary,encrypted_icon,encrypted_category,parent_id,is_sub_chat,budget_limit,budget_spent",
                "sort": "created_at",
                "limit": -1,
            },
            admin_required=True,
        ) or []
        
        return {
            "chat_id": chat_id,
            "encrypted_title": chat.get("encrypted_title"),
            "encrypted_chat_summary": chat.get("encrypted_chat_summary"),
            "encrypted_follow_up_request_suggestions": chat.get("encrypted_follow_up_request_suggestions"),
            "encrypted_icon": chat.get("encrypted_icon"),  # Icon name encrypted with chat key
            "encrypted_category": chat.get("encrypted_category"),  # Category name encrypted with chat key
            "messages": messages or [],
            "embeds": embeds or [],
            "embed_keys": embed_keys or [],
            "sub_chats": sub_chats,
            "code_run_outputs": code_run_outputs,
            "message_highlights": message_highlights,
            "share_pii": share_pii,
            "share_highlights": bool(share_highlights),
            "is_dummy": False  # Internal flag, not sent to client
        }
        
    except Exception as e:
        logger.error(f"Error fetching shared chat {chat_id}: {e}", exc_info=True)
        # On error, return dummy data to prevent information leakage
        dummy_data = generate_dummy_encrypted_data(chat_id)
        dummy_data.pop("is_dummy", None)
        return dummy_data

@router.get("/chat/{chat_id}/manifest")
@limiter.limit("30/minute")
async def get_shared_chat_manifest(
    request: Request,
    chat_id: str,
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """Get shared-chat metadata and auxiliary encrypted records without messages."""
    try:
        chat, dummy = await get_shared_chat_or_dummy(chat_id, directus_service)
        if dummy is not None or chat is None:
            return dummy or generate_dummy_encrypted_data(chat_id)
        payload = shared_chat_metadata_payload(chat_id, chat)
        payload.update(await get_shared_chat_auxiliary_payload(chat_id, chat, directus_service))
        payload["messages"] = []
        return payload
    except Exception as e:
        logger.error(f"Error fetching shared chat manifest {chat_id}: {e}", exc_info=True)
        dummy_data = generate_dummy_encrypted_data(chat_id)
        dummy_data.pop("is_dummy", None)
        return dummy_data

@router.get("/chat/{chat_id}/messages")
@limiter.limit("60/minute")
async def get_shared_chat_message_window(
    request: Request,
    chat_id: str,
    before_timestamp: int = Query(default=2147483647),
    before_message_id: Optional[str] = Query(default=None),
    target_message_id: Optional[str] = Query(default=None),
    limit: int = Query(default=40, ge=1, le=100),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """Get a bounded encrypted shared-chat message window."""
    try:
        if not isinstance(before_message_id, str):
            before_message_id = None
        if not isinstance(target_message_id, str):
            target_message_id = None
        chat, dummy = await get_shared_chat_or_dummy(chat_id, directus_service)
        if dummy is not None or chat is None:
            return {"chat_id": chat_id, "messages": (dummy or {}).get("messages", []), "has_more": False, "next_before_timestamp": None}
        if target_message_id:
            target_message = await directus_service.chat.get_message_for_chat_by_client_id(
                chat_id=chat_id,
                message_id=target_message_id,
            )
            if target_message:
                before_timestamp = min(int(before_timestamp), int(target_message.get("created_at") or before_timestamp))
        messages = await directus_service.chat.get_messages_for_chat_before_timestamp(
            chat_id=chat_id,
            before_timestamp=before_timestamp,
            before_message_id=before_message_id,
            limit=limit + 1,
        )
        has_more = len(messages) > limit
        if has_more:
            messages = messages[1:]
        messages = sanitize_shared_pii(messages, bool(chat.get("share_pii", False)))
        next_before_timestamp = None
        next_before_message_id = None
        if has_more and messages:
            import json
            try:
                first_message = json.loads(messages[0])
                next_before_timestamp = int(first_message.get("created_at"))
                next_before_message_id = first_message.get("message_id") or first_message.get("client_message_id") or first_message.get("id")
            except Exception:
                next_before_timestamp = None
                next_before_message_id = None
        return {
            "chat_id": chat_id,
            "messages": messages,
            "has_more": has_more,
            "next_before_timestamp": next_before_timestamp,
            "next_before_message_id": next_before_message_id,
            "target_message_id": target_message_id,
        }
    except Exception as e:
        logger.error(f"Error fetching shared chat messages {chat_id}: {e}", exc_info=True)
        dummy_data = generate_dummy_encrypted_data(chat_id)
        dummy_data.pop("is_dummy", None)
        return {"chat_id": chat_id, "messages": dummy_data.get("messages", []), "has_more": False, "next_before_timestamp": None}

@router.get("/chat/{chat_id}/og-metadata")
@limiter.limit("60/minute")  # Higher limit since this is used for every share page load
async def get_og_metadata(
    request: Request,
    chat_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> Dict[str, Any]:
    """
    Get OG metadata (title, description, image) for a shared chat.

    This endpoint is called by the SvelteKit server route to generate OG tags.
    It decrypts shared_encrypted_title and shared_encrypted_summary using the
    shared vault key.

    Returns:
    - Real metadata if chat exists and is_private = false
    - Fallback metadata if chat doesn't exist or is_private = true

    Security:
    - Rate limited
    - Returns consistent fallback for non-existent/private chats
    """
    try:
        # Fetch chat metadata
        logger.debug(f"Fetching OG metadata for chat {chat_id}")
        chat = await directus_service.chat.get_chat_metadata(chat_id)

        if not chat:
            # Chat doesn't exist - return fallback
            logger.warning(f"Chat {chat_id} not found for OG metadata, returning fallback")
            return {
                "title": "Shared Chat - OpenMates",
                "description": "View this shared conversation on OpenMates",
                "image": "/og-images/default-chat.png",
                "category": None
            }

        # Log what we received from Directus
        logger.debug(f"Chat {chat_id} metadata retrieved: "
                    f"is_private={chat.get('is_private')}, is_shared={chat.get('is_shared')}, "
                    f"has_shared_encrypted_title={bool(chat.get('shared_encrypted_title'))}, "
                    f"has_shared_encrypted_summary={bool(chat.get('shared_encrypted_summary'))}")

        # Check if chat is private
        is_private = chat.get("is_private", False)
        if is_private:
            # Chat is private - return fallback
            logger.info(f"Chat {chat_id} is private, returning fallback OG metadata")
            return {
                "title": "Shared Chat - OpenMates",
                "description": "View this shared conversation on OpenMates",
                "image": "/og-images/default-chat.png",
                "category": None
            }

        # Chat exists and is shared - decrypt metadata
        shared_encrypted_title = chat.get("shared_encrypted_title")
        shared_encrypted_summary = chat.get("shared_encrypted_summary")

        # Log what we received to help debug OG tag issues
        logger.debug(
            f"OG metadata for chat {chat_id}: "
            f"has_shared_encrypted_title={bool(shared_encrypted_title)}, "
            f"has_shared_encrypted_summary={bool(shared_encrypted_summary)}, "
            f"is_private={chat.get('is_private', False)}, "
            f"is_shared={chat.get('is_shared', False)}"
        )

        title = "Shared Chat - OpenMates"  # Fallback
        description = "View this shared conversation on OpenMates"  # Fallback

        # Decrypt title if available
        if shared_encrypted_title:
            try:
                title = await encryption_service.decrypt(
                    shared_encrypted_title,
                    key_name="shared-content-metadata"
                )
                logger.info(
                    f"Decrypted title for chat {chat_id} "
                    f"(length={len(title) if isinstance(title, str) else 0})"
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt shared_encrypted_title for chat {chat_id}: {e}")
        else:
            logger.warning(f"No shared_encrypted_title found for chat {chat_id} - using fallback")

        # Decrypt summary if available
        if shared_encrypted_summary:
            try:
                description = await encryption_service.decrypt(
                    shared_encrypted_summary,
                    key_name="shared-content-metadata"
                )
                logger.info(
                    f"Decrypted summary for chat {chat_id} "
                    f"(length={len(description) if isinstance(description, str) else 0})"
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt shared_encrypted_summary for chat {chat_id}: {e}")
        else:
            logger.warning(f"No shared_encrypted_summary found for chat {chat_id} - using fallback")

        # Get category for OG image selection
        # Note: We can't decrypt encrypted_category here because it's encrypted with
        # the user's chat key, not the shared vault key. For now, we'll use the default image.
        # In the future, we could add a shared_category field if needed.
        category = None

        # Determine OG image based on category (fallback to default for now)
        og_image = "/og-images/default-chat.png"

        return {
            "title": title,
            "description": description,
            "image": og_image,
            "category": category
        }

    except Exception as e:
        logger.error(f"Error fetching OG metadata for chat {chat_id}: {e}", exc_info=True)
        # On error, return fallback to prevent information leakage
        return {
            "title": "Shared Chat - OpenMates",
            "description": "View this shared conversation on OpenMates",
            "image": "/og-images/default-chat.png",
            "category": None
        }

@router.post("/chat/metadata")
@limiter.limit("30/minute")  # Prevent abuse of metadata updates
async def update_share_metadata(
    request: Request,
    payload: ShareChatMetadataUpdate,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> Dict[str, Any]:
    """
    Update OG metadata for a shared chat.

    This endpoint is called when a user shares a chat to update the
    shared_encrypted_title and shared_encrypted_summary fields.

    The metadata is encrypted with the shared vault key (shared-content-metadata)
    so the server can decrypt it for OG tag generation without user context.

    Requires authentication - user must own the chat.
    """
    try:
        chat_id = payload.chat_id

        # Verify chat exists
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Verify user owns the chat by comparing hashed user IDs
        chat_hashed_user_id = chat.get("hashed_user_id")
        current_user_hashed_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        if chat_hashed_user_id != current_user_hashed_id:
            logger.warning(f"User {current_user.id} attempted to update metadata for chat {chat_id} owned by different user")
            raise HTTPException(status_code=403, detail="You do not have permission to update this chat")
        
        # Encrypt metadata with shared vault key
        shared_vault_key = "shared-content-metadata"
        
        updates = {}
        if payload.title is not None:
            encrypted_title, _ = await encryption_service.encrypt(
                payload.title,
                key_name=shared_vault_key
            )
            updates["shared_encrypted_title"] = encrypted_title
        
        if payload.summary is not None:
            encrypted_summary, _ = await encryption_service.encrypt(
                payload.summary,
                key_name=shared_vault_key
            )
            updates["shared_encrypted_summary"] = encrypted_summary
        
        if payload.category is not None:
            encrypted_category, _ = await encryption_service.encrypt(
                payload.category,
                key_name=shared_vault_key
            )
            updates["shared_encrypted_category"] = encrypted_category
            
        if payload.icon is not None:
            encrypted_icon, _ = await encryption_service.encrypt(
                payload.icon,
                key_name=shared_vault_key
            )
            updates["shared_encrypted_icon"] = encrypted_icon

        if payload.follow_up_suggestions is not None:
            import json
            encrypted_follow_ups, _ = await encryption_service.encrypt(
                json.dumps(payload.follow_up_suggestions),
                key_name=shared_vault_key
            )
            updates["shared_encrypted_follow_up_suggestions"] = encrypted_follow_ups

        payload_fields_set = getattr(payload, "model_fields_set", None)
        if payload_fields_set is None:
            payload_fields_set = getattr(payload, "__fields_set__", set())
        if "encrypted_shared_short_url" in payload_fields_set:
            updates["encrypted_shared_short_url"] = payload.encrypted_shared_short_url
        
        # Update sharing status: set is_shared=true and is_private=false when sharing
        if payload.is_shared is not None:
            updates["is_shared"] = payload.is_shared
            # When sharing (is_shared=true), ensure is_private=false
            if payload.is_shared:
                updates["is_private"] = False

        if payload.share_pii is not None:
            updates["share_pii"] = payload.share_pii

        if payload.share_highlights is not None:
            updates["share_highlights"] = payload.share_highlights

        # Update community sharing preference
        if payload.share_with_community is not None:
            updates["share_with_community"] = payload.share_with_community
        
        # Update chat in database
        if updates:
            # Log what we're about to update (but not the encrypted values for security)
            logger.info(f"Updating chat {chat_id} with fields: {list(updates.keys())}")
            logger.debug(f"Update values: is_shared={updates.get('is_shared')}, is_private={updates.get('is_private')}, "
                        f"has_title={bool(updates.get('shared_encrypted_title'))}, "
                        f"has_summary={bool(updates.get('shared_encrypted_summary'))}")
            
            # Request the updated fields in the response to verify they were saved
            # Directus will return the updated item with these fields if the update succeeds
            params = {
                'fields': 'id,shared_encrypted_title,shared_encrypted_summary,shared_encrypted_category,shared_encrypted_icon,shared_encrypted_follow_up_suggestions,encrypted_shared_short_url,is_shared,is_private,share_pii,share_highlights'
            }
            updated_item = await directus_service.update_item(
                "chats",
                chat_id,
                updates,
                params=params,
                admin_required=True,
            )
            if updated_item is None:
                logger.error(f"Failed to update chat {chat_id} - update_item returned None")
                raise HTTPException(status_code=500, detail="Failed to update chat in database")
            
            # Log what Directus returned from the update
            if isinstance(updated_item, dict):
                logger.debug(f"Directus update response for chat {chat_id}: "
                           f"has_shared_encrypted_title={bool(updated_item.get('shared_encrypted_title'))}, "
                           f"has_shared_encrypted_summary={bool(updated_item.get('shared_encrypted_summary'))}, "
                           f"is_shared={updated_item.get('is_shared')}, is_private={updated_item.get('is_private')}")
            else:
                logger.debug(f"Directus update response for chat {chat_id} is not a dict: {type(updated_item)}")
            
            logger.info(f"Updated OG metadata and sharing status for chat {chat_id}")
            
            # Verify the update was successful by reading back the chat metadata
            # This ensures the data is committed and visible before returning
            # Use a small delay to allow Directus to commit the transaction
            import asyncio
            await asyncio.sleep(0.1)  # 100ms delay to ensure Directus has committed
            
            try:
                # Force a fresh read by using no_cache=True (which get_chat_metadata already does)
                # Try multiple times with increasing delays in case Directus needs time to commit
                updated_chat = None
                for attempt in range(3):
                    if attempt > 0:
                        await asyncio.sleep(0.2 * attempt)  # 200ms, 400ms delays
                    updated_chat = await directus_service.chat.get_chat_metadata(
                        chat_id,
                        admin_required=True,
                    )
                    if updated_chat:
                        has_title = bool(updated_chat.get("shared_encrypted_title"))
                        has_summary = bool(updated_chat.get("shared_encrypted_summary"))
                        # If we have the fields we expect, break early
                        if (payload.title is None or has_title) and (payload.summary is None or has_summary):
                            break
                
                if updated_chat:
                    # Log what was actually stored to help debug OG tag issues
                    has_title = bool(updated_chat.get("shared_encrypted_title"))
                    has_summary = bool(updated_chat.get("shared_encrypted_summary"))
                    is_shared = updated_chat.get("is_shared", False)
                    is_private = updated_chat.get("is_private", True)
                    
                    # Log all fields to see what we got
                    logger.info(
                        f"Verified update for chat {chat_id} (attempt {attempt + 1}): "
                        f"is_shared={is_shared}, is_private={is_private}, "
                        f"has_title={has_title}, has_summary={has_summary}"
                    )
                    
                    # Log field presence/length only (never ciphertext previews)
                    if updated_chat.get("shared_encrypted_title"):
                        title_len = len(str(updated_chat.get("shared_encrypted_title")))
                        logger.debug(f"shared_encrypted_title present for chat {chat_id} (length: {title_len})")
                    else:
                        logger.warning(f"shared_encrypted_title is missing or empty for chat {chat_id}")
                    
                    if updated_chat.get("shared_encrypted_summary"):
                        summary_len = len(str(updated_chat.get("shared_encrypted_summary")))
                        logger.debug(f"shared_encrypted_summary present for chat {chat_id} (length: {summary_len})")
                    else:
                        logger.warning(f"shared_encrypted_summary is missing or empty for chat {chat_id}")
                    
                    # If the expected fields are missing, log a warning
                    if payload.title is not None and not has_title:
                        logger.error(f"Title update FAILED for chat {chat_id} - field not found after update. "
                                   f"Expected to set title, but field is missing.")
                    if payload.summary is not None and not has_summary:
                        logger.error(f"Summary update FAILED for chat {chat_id} - field not found after update. "
                                   f"Expected to set summary, but field is missing.")
                else:
                    logger.error(f"Could not verify update for chat {chat_id} - chat not found after update")
            except Exception as e:
                logger.error(f"Error verifying update for chat {chat_id}: {e}", exc_info=True)
        
        # If user wants to share with community, send an email to admin with the share link
        # (including the encryption key). No demo_chat creation or approval pipeline needed.
        if payload.share_with_community and payload.share_link:
            try:
                admin_email = os.getenv("ADMIN_NOTIFY_EMAIL", "notify@openmates.org")

                from backend.core.api.app.tasks.celery_config import app
                app.send_task(
                    name='app.tasks.email_tasks.issue_report_email_task.send_issue_report_email',
                    kwargs={
                        "admin_email": admin_email,
                        "issue_id": f"community-share-{chat_id[:8]}",
                        "issue_title": f"Community chat suggestion: {payload.title or 'Untitled'}",
                        "issue_description": (
                            f"A user wants to share this chat with the community.\n\n"
                            f"**Title:** {payload.title or 'Untitled'}\n"
                            f"**Summary:** {payload.summary or 'No summary'}\n"
                            f"**Category:** {payload.category or 'N/A'}\n\n"
                            f"**Share link (with encryption key):**\n{payload.share_link}"
                        ),
                        "language": "en",
                    },
                    queue='email'
                )
                logger.info(f"Dispatched community share email for chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to dispatch community share email for chat {chat_id}: {e}")
        
        return {"success": True, "chat_id": chat_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating share metadata for chat {payload.chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update share metadata")

@router.post("/chat/unshare")
async def unshare_chat(
    payload: UnshareChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Unshare a chat by setting is_private = true.

    This also clears shared_encrypted_title and shared_encrypted_summary
    to remove OG metadata.

    Requires authentication - user must own the chat.
    """
    try:
        chat_id = payload.chat_id

        # Verify chat exists
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Verify user owns the chat by comparing hashed user IDs
        chat_hashed_user_id = chat.get("hashed_user_id")
        current_user_hashed_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        if chat_hashed_user_id != current_user_hashed_id:
            logger.warning(f"User {current_user.id} attempted to unshare chat {chat_id} owned by different user")
            raise HTTPException(status_code=403, detail="You do not have permission to unshare this chat")
        
        # Set is_private = true, is_shared = false, and clear shared metadata
        updates = {
            "is_private": True,
            "is_shared": False,
            "share_with_community": False,
            "shared_encrypted_title": None,
            "shared_encrypted_summary": None,
            "shared_encrypted_category": None,
            "shared_encrypted_icon": None,
            "shared_encrypted_follow_up_suggestions": None,
            "encrypted_shared_short_url": None,
        }
        
        await directus_service.update_item("chats", chat_id, updates)
        try:
            now = int(time.time())
            short_links = await directus_service.get_items(
                SHORT_URL_COLLECTION,
                params={
                    "filter[content_type][_eq]": "chat",
                    "filter[content_id][_eq]": chat_id,
                    "filter[revoked_at][_null]": True,
                    "fields": "id",
                    "limit": -1,
                },
                admin_required=True,
            )
            for short_link in short_links or []:
                short_link_id = short_link.get("id")
                if short_link_id:
                    await directus_service.update_item(
                        SHORT_URL_COLLECTION,
                        short_link_id,
                        {"revoked_at": now, "updated_at": now},
                        admin_required=True,
                    )
        except Exception as exc:
            logger.error("Failed to revoke short links for unshared chat %s: %s", chat_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to revoke short links")
        logger.info(f"Unshared chat {chat_id}")
        
        return {"success": True, "chat_id": chat_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsharing chat {payload.chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unshare chat")

@router.get("/time")
@limiter.limit("60/minute")  # Allow more requests since this is lightweight, but still prevent abuse
async def get_server_time(request: Request) -> Dict[str, Any]:
    """
    Get current server time in Unix timestamp (seconds).

    Used for expiration validation of share links.
    """
    return {
        "timestamp": int(time.time()),
        "server_time": int(time.time())
    }

# --- Embed Sharing Endpoints ---

class ShareEmbedMetadataUpdate(BaseModel):
    """Request model for updating OG metadata when sharing an embed"""
    embed_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    is_shared: Optional[bool] = None

def generate_dummy_encrypted_embed_data(embed_id: str) -> Dict[str, Any]:
    """
    Generate deterministic dummy encrypted data for an embed ID.
    Prevents enumeration attacks by making non-existent embeds look like real ones.
    """
    # Use embed_id as seed for deterministic dummy data
    seed = hashlib.sha256(embed_id.encode()).digest()

    # Generate deterministic "encrypted" data
    import base64
    dummy_title = base64.b64encode(seed[:16]).decode('utf-8')
    dummy_content = base64.b64encode(seed[16:48]).decode('utf-8')

    return {
        "embed_id": embed_id,
        "encrypted_type": "app_skill_use",  # Generic type for dummy data
        "encrypted_content": dummy_content,
        "encrypted_text_preview": dummy_title,
        "status": "finished",
        "is_dummy": True  # Internal flag
    }

@router.get("/embed/{embed_id}")
@limiter.limit("30/minute")  # Same rate limit as chat sharing
async def get_shared_embed(
    request: Request,
    embed_id: str,
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get encrypted embed data for a shared embed.

    Returns:
    - Real encrypted embed data and child embeds if embed exists and is shared
    - Dummy encrypted data if embed doesn't exist or is private

    Security:
    - Rate limited to prevent brute force attacks
    - Returns consistent dummy data for non-existent embeds
    - Only returns real data if is_private is false
    """
    try:
        # Fetch embed from database
        embed = await directus_service.embed.get_embed_by_id(embed_id)

        if not embed:
            # Embed doesn't exist - return dummy data to prevent enumeration
            logger.debug(f"Embed {embed_id} not found, returning dummy data")
            dummy_data = generate_dummy_encrypted_embed_data(embed_id)
            dummy_data.pop("is_dummy", None)
            return {"embed": dummy_data, "child_embeds": [], "embed_keys": [], "code_run_outputs": []}

        # Check if embed is private (not shared)
        # Use is_private field (mirrors chat sharing structure)
        # Default to False (shareable) if field doesn't exist (for backward compatibility)
        is_private = embed.get("is_private", False)
        if is_private:
            # Embed is private (unshared) - return dummy data
            logger.debug(f"Embed {embed_id} is private (unshared), returning dummy data")
            dummy_data = generate_dummy_encrypted_embed_data(embed_id)
            dummy_data.pop("is_dummy", None)
            return {"embed": dummy_data, "child_embeds": [], "embed_keys": [], "code_run_outputs": []}

        # Embed exists and is shared - return real encrypted data
        logger.debug(f"Returning real encrypted data for shared embed {embed_id}")
        
        # Log ciphertext presence/length only (never ciphertext preview)
        encrypted_content = embed.get("encrypted_content")
        if encrypted_content:
            logger.debug(f"Embed {embed_id} encrypted_content present (length: {len(encrypted_content)} chars)")
        else:
            logger.warning(f"Embed {embed_id} has no encrypted_content field or it's None/empty")

        # Get child embeds if this is a composite embed (e.g., web search with website children)
        child_embeds = []
        embed_ids = embed.get("embed_ids")  # Array of child embed IDs
        if embed_ids and isinstance(embed_ids, list):
            for child_embed_id in embed_ids:
                child_embed = await directus_service.embed.get_embed_by_id(child_embed_id)
                if child_embed:
                    child_embeds.append(child_embed)

        # Get embed_keys for this embed and its children
        # These contain wrapped keys that allow shared embed recipients to decrypt embeds
        embed_keys = []

        # Get keys for the main embed
        main_embed_keys = await directus_service.embed.get_embed_keys_by_embed_id(embed_id)
        if main_embed_keys:
            embed_keys.extend(main_embed_keys)

        # Get keys for child embeds
        for child_embed in child_embeds:
            child_embed_id = child_embed.get("embed_id")
            if child_embed_id:
                child_keys = await directus_service.embed.get_embed_keys_by_embed_id(child_embed_id)
                if child_keys:
                    embed_keys.extend(child_keys)

        code_run_outputs = await directus_service.get_items(
            "code_run_outputs",
            params={
                "filter[embed_id][_eq]": embed_id,
                "fields": "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at",
                "sort": "-updated_at",
                "limit": 1,
            },
            admin_required=True,
        ) or []

        return {
            "embed": embed,
            "child_embeds": child_embeds,
            "embed_keys": embed_keys,
            "code_run_outputs": code_run_outputs,
        }

    except Exception as e:
        logger.error(f"Error fetching shared embed {embed_id}: {e}", exc_info=True)
        # On error, return dummy data to prevent information leakage
        dummy_data = generate_dummy_encrypted_embed_data(embed_id)
        dummy_data.pop("is_dummy", None)
        return {"embed": dummy_data, "child_embeds": [], "embed_keys": [], "code_run_outputs": []}

@router.get("/embed/{embed_id}/og-metadata")
@limiter.limit("60/minute")
async def get_embed_og_metadata(
    request: Request,
    embed_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> Dict[str, Any]:
    """
    Get OG metadata (title, description, image) for a shared embed.

    This endpoint is called by the SvelteKit server route to generate OG tags.
    It decrypts shared_encrypted_title and shared_encrypted_description using the
    shared vault key.

    Returns:
    - Real metadata if embed exists and is shared
    - Fallback metadata if embed doesn't exist or is private
    """
    try:
        # Fetch embed from database
        embed = await directus_service.embed.get_embed_by_id(embed_id)

        if not embed:
            logger.debug(f"Embed {embed_id} not found for OG metadata, using fallback")
            return {
                "title": "Shared Embed - OpenMates",
                "description": "View this shared content on OpenMates",
                "image": "/og-images/default-embed.png",
                "type": "embed"
            }

        # Check if embed is private (not shared)
        # Use is_private field (mirrors chat sharing structure)
        # Default to False (shareable) if field doesn't exist (for backward compatibility)
        is_private = embed.get("is_private", False)
        if is_private:
            logger.debug(f"Embed {embed_id} is private (unshared), using fallback metadata")
            return {
                "title": "Shared Embed - OpenMates",
                "description": "View this shared content on OpenMates",
                "image": "/og-images/default-embed.png",
                "type": "embed"
            }

        # Decrypt metadata for OG tags
        shared_encrypted_title = embed.get("shared_encrypted_title")
        shared_encrypted_description = embed.get("shared_encrypted_description")
        embed_type = embed.get("encrypted_type", "embed")  # This might be encrypted, but we'll use as fallback

        title = "Shared Embed - OpenMates"  # Fallback
        description = "View this shared content on OpenMates"  # Fallback

        # Decrypt title if available
        if shared_encrypted_title:
            try:
                title = await encryption_service.decrypt(
                    shared_encrypted_title,
                    key_name="shared-content-metadata"
                )
                logger.info(
                    f"Decrypted title for embed {embed_id} "
                    f"(length={len(title) if isinstance(title, str) else 0})"
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt shared_encrypted_title for embed {embed_id}: {e}")

        # Decrypt description if available
        if shared_encrypted_description:
            try:
                description = await encryption_service.decrypt(
                    shared_encrypted_description,
                    key_name="shared-content-metadata"
                )
                logger.info(
                    f"Decrypted description for embed {embed_id} "
                    f"(length={len(description) if isinstance(description, str) else 0})"
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt shared_encrypted_description for embed {embed_id}: {e}")

        # Determine OG image based on embed type
        og_image = "/og-images/default-embed.png"
        if "video" in str(embed_type).lower():
            og_image = "/og-images/video-embed.png"
        elif "website" in str(embed_type).lower():
            og_image = "/og-images/website-embed.png"
        elif "transcript" in str(embed_type).lower():
            og_image = "/og-images/transcript-embed.png"

        return {
            "title": title,
            "description": description,
            "image": og_image,
            "type": embed_type
        }

    except Exception as e:
        logger.error(f"Error fetching OG metadata for embed {embed_id}: {e}", exc_info=True)
        # On error, return fallback
        return {
            "title": "Shared Embed - OpenMates",
            "description": "View this shared content on OpenMates",
            "image": "/og-images/default-embed.png",
            "type": "embed"
        }

@router.post("/embed/metadata")
@limiter.limit("30/minute")
async def update_embed_share_metadata(
    request: Request,
    payload: ShareEmbedMetadataUpdate,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> Dict[str, Any]:
    """
    Update OG metadata for a shared embed.

    This endpoint is called when a user shares an embed to update the
    shared_encrypted_title and shared_encrypted_description fields.

    Requires authentication - user must own the embed.
    """
    try:
        embed_id = payload.embed_id

        # Verify embed exists
        embed = await directus_service.embed.get_embed_by_id(embed_id)
        if not embed:
            raise HTTPException(status_code=404, detail="Embed not found")

        # Verify user owns the embed by comparing hashed user IDs
        embed_hashed_user_id = embed.get("hashed_user_id")
        current_user_hashed_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        if embed_hashed_user_id != current_user_hashed_id:
            logger.warning(f"User {current_user.id} attempted to update metadata for embed {embed_id} owned by different user")
            raise HTTPException(status_code=403, detail="You do not have permission to update this embed")

        # Encrypt metadata with shared vault key
        shared_vault_key = "shared-content-metadata"

        updates = {}
        if payload.title is not None:
            encrypted_title, _ = await encryption_service.encrypt(
                payload.title,
                key_name=shared_vault_key
            )
            updates["shared_encrypted_title"] = encrypted_title

        if payload.description is not None:
            encrypted_description, _ = await encryption_service.encrypt(
                payload.description,
                key_name=shared_vault_key
            )
            updates["shared_encrypted_description"] = encrypted_description

        # Update is_private and is_shared fields (mirrors chat sharing structure)
        if payload.is_shared is not None:
            # When sharing (is_shared=true), ensure is_private=false
            # When unsharing (is_shared=false), set is_private=true
            if payload.is_shared:
                updates["is_private"] = False
                updates["is_shared"] = True
            else:
                updates["is_private"] = True
                updates["is_shared"] = False

        # Update the embed
        await directus_service.update_item("embeds", embed_id, updates)

        logger.info(f"Updated share metadata for embed {embed_id}: {list(updates.keys())}")

        return {"success": True, "embed_id": embed_id, "updated_fields": list(updates.keys())}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating share metadata for embed {payload.embed_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update embed metadata")


# --- Short URL Sharing Endpoints ---
# Durable short URLs use /s/{token}#shortKey. The server receives only the token
# and stores only an opaque encrypted URL blob; the decryption key remains in the
# URL fragment and is never sent over HTTP.

# Validation: token must be 6-12 alphanumeric chars (base62)
SHORT_URL_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]{6,12}$")
# Max size for encrypted URL blob (base64-encoded AES-GCM ciphertext)
SHORT_URL_MAX_BLOB_SIZE = 4096
SHORT_URL_MAX_TTL_SECONDS = 7_776_000  # 90 days, matching the share-key max
SHORT_URL_COLLECTION = "share_short_links"

SHORT_URL_FIELDS = (
    "id,token,encrypted_url,content_type,content_id,hashed_user_id,"
    "password_protected,expires_at,revoked_at,created_at,updated_at"
)

PROTECTED_CHAT_TITLE = "Password protected chat"
PROTECTED_CHAT_DESCRIPTION = "Open this password-protected chat on OpenMates."
DEFAULT_CHAT_TITLE = "Shared Chat - OpenMates"
DEFAULT_CHAT_DESCRIPTION = "View this shared conversation on OpenMates"
DEFAULT_EMBED_TITLE = "Shared Embed - OpenMates"
DEFAULT_EMBED_DESCRIPTION = "View this shared content on OpenMates"

OG_IMAGE_WIDTH = 1200
OG_IMAGE_HEIGHT = 630

OG_CATEGORY_GRADIENTS: Dict[str, tuple[str, str]] = {
    "software_development": ("#155D91", "#42ABF4"),
    "business_development": ("#004040", "#008080"),
    "medical_health": ("#FD50A0", "#F42C2D"),
    "legal_law": ("#239CFF", "#005BA5"),
    "openmates_official": ("#6366f1", "#4f46e5"),
    "maker_prototyping": ("#EA7600", "#FBAB59"),
    "marketing_sales": ("#FF8C00", "#F4B400"),
    "finance": ("#119106", "#15780D"),
    "design": ("#101010", "#2E2E2E"),
    "electrical_engineering": ("#233888", "#2E4EC8"),
    "movies_tv": ("#00C2C5", "#3170DC"),
    "history": ("#4989F2", "#2F44BF"),
    "science": ("#CE5B06", "#8F220E"),
    "life_coach_psychology": ("#FDB250", "#F42C2D"),
    "cooking_food": ("#FD8450", "#F42C2D"),
    "activism": ("#F53D00", "#F56200"),
    "general_knowledge": ("#DE1E66", "#FF763B"),
    "onboarding_support": ("#6364FF", "#9B6DFF"),
}


class CreateShortUrlRequest(BaseModel):
    """Request model for creating a short URL."""
    token: str = Field(..., description="Lookup token (6-12 base62 chars, generated client-side)")
    encrypted_url: str = Field(..., description="AES-GCM encrypted share URL blob (opaque to server)")
    content_type: Literal["chat", "embed"] = Field(..., description="Shared content type")
    content_id: str = Field(..., description="Chat ID or embed ID associated with the share")
    password_protected: bool = Field(default=False, description="Whether crawler metadata must hide content metadata")
    ttl_seconds: Optional[int] = Field(
        default=None,
        description="Optional time-to-live in seconds. Null means no expiration.",
        ge=60,
        le=SHORT_URL_MAX_TTL_SECONDS,
    )


class CreateShortUrlResponse(BaseModel):
    """Response model for short URL creation."""
    success: bool = Field(..., description="Whether the short URL was created successfully")
    expires_at: Optional[int] = Field(default=None, description="Unix timestamp when the short URL expires, or null")


class ResolveShortUrlResponse(BaseModel):
    """Response model for short URL resolution."""
    encrypted_url: str = Field(..., description="The encrypted share URL blob")


class ShortUrlStorageUnavailable(Exception):
    """Raised when durable short-link storage is temporarily unavailable."""


def _short_url_image_path(token: str) -> str:
    return f"/v1/share/short-url/{token}/og-image.png"


async def _get_short_link_record(token: str, directus_service: DirectusService) -> Optional[Dict[str, Any]]:
    items = await directus_service.get_items(
        SHORT_URL_COLLECTION,
        params={
            "filter[token][_eq]": token,
            "fields": SHORT_URL_FIELDS,
            "limit": 1,
        },
        admin_required=True,
    )
    if not items:
        return None
    return items[0]


def _short_link_is_expired_or_revoked(record: Dict[str, Any]) -> bool:
    if record.get("revoked_at"):
        return True
    expires_at = record.get("expires_at")
    return bool(expires_at and int(expires_at) <= int(time.time()))


async def _verify_short_link_target(
    payload: CreateShortUrlRequest,
    current_user: User,
    directus_service: DirectusService,
) -> str:
    current_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    if payload.content_type == "chat":
        chat = await directus_service.chat.get_chat_metadata(payload.content_id, admin_required=True)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        if chat.get("hashed_user_id") != current_user_hash:
            raise HTTPException(status_code=403, detail="You do not have permission to share this chat")
        return current_user_hash

    embed = await directus_service.embed.get_embed_by_id(payload.content_id)
    if not embed:
        raise HTTPException(status_code=404, detail="Embed not found")
    if embed.get("hashed_user_id") != current_user_hash:
        raise HTTPException(status_code=403, detail="You do not have permission to share this embed")
    return current_user_hash


async def _create_directus_item(directus_service: DirectusService, collection: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    created = await directus_service.create_item(collection, payload, admin_required=True)
    if isinstance(created, tuple):
        success, item = created
        if not success:
            raise ShortUrlStorageUnavailable(str(item))
        return item or payload
    if isinstance(created, dict):
        return created
    raise ShortUrlStorageUnavailable(f"Unexpected Directus create_item result: {type(created).__name__}")


async def _store_short_url_cache_fallback(
    payload: CreateShortUrlRequest,
    cache_service: CacheService,
    now: int,
) -> Optional[int]:
    """Store a non-durable short link when the durable CMS collection is unavailable."""
    ttl_seconds = payload.ttl_seconds or cache_config.SHORT_URL_MAX_TTL
    stored = await cache_service.store_short_url(payload.token, payload.encrypted_url, ttl_seconds)
    if not stored:
        raise HTTPException(status_code=500, detail="Failed to store short URL")
    return now + ttl_seconds


async def _decrypt_shared_metadata(
    encrypted_value: Optional[str],
    fallback: str,
    encryption_service: EncryptionService,
) -> str:
    if not encrypted_value:
        return fallback
    try:
        value = await encryption_service.decrypt(encrypted_value, key_name="shared-content-metadata")
        return value if isinstance(value, str) and value.strip() else fallback
    except Exception as exc:
        logger.warning("Failed to decrypt shared metadata for short URL preview: %s", exc)
        return fallback


async def _build_short_url_metadata(
    token: str,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
) -> Dict[str, Any]:
    fallback = {
        "title": DEFAULT_CHAT_TITLE,
        "description": DEFAULT_CHAT_DESCRIPTION,
        "image": _short_url_image_path(token),
        "content_type": "chat",
        "password_protected": False,
        "category": None,
        "icon": None,
    }
    if not SHORT_URL_TOKEN_PATTERN.match(token):
        return fallback

    record = await _get_short_link_record(token, directus_service)
    if not record or _short_link_is_expired_or_revoked(record):
        return fallback

    content_type = record.get("content_type") or "chat"
    password_protected = bool(record.get("password_protected"))
    if content_type == "chat" and password_protected:
        return {
            "title": PROTECTED_CHAT_TITLE,
            "description": PROTECTED_CHAT_DESCRIPTION,
            "image": _short_url_image_path(token),
            "content_type": "chat",
            "password_protected": True,
            "category": "openmates_official",
            "icon": "lock",
        }

    if content_type == "embed":
        return {
            "title": DEFAULT_EMBED_TITLE,
            "description": DEFAULT_EMBED_DESCRIPTION,
            "image": "/images/og-image.jpg",
            "content_type": "embed",
            "password_protected": password_protected,
            "category": None,
            "icon": None,
        }

    chat = await directus_service.chat.get_chat_metadata(record.get("content_id"), admin_required=True)
    if not chat or chat.get("is_private", False):
        return fallback

    title = await _decrypt_shared_metadata(chat.get("shared_encrypted_title"), DEFAULT_CHAT_TITLE, encryption_service)
    summary = await _decrypt_shared_metadata(chat.get("shared_encrypted_summary"), DEFAULT_CHAT_DESCRIPTION, encryption_service)
    category = await _decrypt_shared_metadata(chat.get("shared_encrypted_category"), "general_knowledge", encryption_service)
    icon = await _decrypt_shared_metadata(chat.get("shared_encrypted_icon"), "chat", encryption_service)
    return {
        "title": title,
        "description": summary,
        "image": _short_url_image_path(token),
        "content_type": "chat",
        "password_protected": False,
        "category": category,
        "icon": icon,
    }


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    color = hex_color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def _wrap_text(draw: Any, text: str, font: Any, max_width: int, max_lines: int) -> List[str]:
    words = (text or "").split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if words and len(lines) == max_lines and " ".join(lines).split() != words[:len(" ".join(lines).split())]:
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines or [""]


def _load_og_font(size: int, bold: bool = False) -> Any:
    from PIL import ImageFont

    font_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in (
        f"/usr/share/fonts/truetype/dejavu/{font_name}",
        f"/usr/local/share/fonts/{font_name}",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_lock_icon(draw: Any, center_x: int, center_y: int, size: int, color: tuple[int, ...]) -> None:
    shackle_width = int(size * 0.56)
    shackle_height = int(size * 0.44)
    body_width = int(size * 0.68)
    body_height = int(size * 0.50)
    shackle_left = center_x - shackle_width // 2
    shackle_top = center_y - int(size * 0.45)
    shackle_right = center_x + shackle_width // 2
    shackle_bottom = shackle_top + shackle_height
    body_left = center_x - body_width // 2
    body_top = center_y - int(size * 0.05)
    body_right = center_x + body_width // 2
    body_bottom = body_top + body_height
    stroke = max(5, size // 14)
    draw.arc((shackle_left, shackle_top, shackle_right, shackle_bottom + shackle_height), 180, 360, fill=color, width=stroke)
    draw.line((shackle_left, center_y - int(size * 0.05), shackle_left, body_top + 4), fill=color, width=stroke)
    draw.line((shackle_right, center_y - int(size * 0.05), shackle_right, body_top + 4), fill=color, width=stroke)
    draw.rounded_rectangle((body_left, body_top, body_right, body_bottom), radius=size // 12, fill=color)


def _draw_chat_icon(draw: Any, center_x: int, center_y: int, size: int, color: tuple[int, ...]) -> None:
    bubble_width = int(size * 0.92)
    bubble_height = int(size * 0.66)
    left = center_x - bubble_width // 2
    top = center_y - bubble_height // 2
    right = center_x + bubble_width // 2
    bottom = center_y + bubble_height // 2
    radius = max(10, size // 7)
    stroke = max(5, size // 15)
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, outline=color, width=stroke)
    tail = [
        (right - int(size * 0.22), bottom - stroke),
        (right - int(size * 0.08), bottom + int(size * 0.18)),
        (right - int(size * 0.36), bottom - stroke),
    ]
    draw.line(tail, fill=color, width=stroke, joint="curve")


def _draw_og_icon(draw: Any, center_x: int, center_y: int, size: int, metadata: Dict[str, Any], color: tuple[int, ...]) -> None:
    if metadata.get("password_protected"):
        _draw_lock_icon(draw, center_x, center_y, size, color)
        return
    _draw_chat_icon(draw, center_x, center_y, size, color)


def _render_short_url_og_png(metadata: Dict[str, Any]) -> bytes:
    import io
    from PIL import Image, ImageDraw

    category = str(metadata.get("category") or "openmates_official")
    start_hex, end_hex = OG_CATEGORY_GRADIENTS.get(category, OG_CATEGORY_GRADIENTS["openmates_official"])
    start = _hex_to_rgb(start_hex)
    end = _hex_to_rgb(end_hex)
    image = Image.new("RGB", (OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT), start)
    pixels = image.load()
    for x in range(OG_IMAGE_WIDTH):
        ratio = x / max(1, OG_IMAGE_WIDTH - 1)
        color = tuple(int(start[channel] * (1 - ratio) + end[channel] * ratio) for channel in range(3))
        for y in range(OG_IMAGE_HEIGHT):
            vertical = 0.92 + 0.08 * (1 - y / OG_IMAGE_HEIGHT)
            pixels[x, y] = tuple(max(0, min(255, int(component * vertical))) for component in color)

    image = image.convert("RGBA")
    overlay = Image.new("RGBA", (OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    white = (255, 255, 255, 255)
    soft_white = (255, 255, 255, 220)
    muted_white = (255, 255, 255, 92)
    title_font = _load_og_font(78, bold=True)
    summary_font = _load_og_font(36)
    brand_font = _load_og_font(28, bold=True)

    icon_center_x = OG_IMAGE_WIDTH // 2
    icon_center_y = 128

    # ChatHeader.svelte uses large decorative side icons when no image bubbles
    # are available. Keep this path server-side only; do not fetch arbitrary
    # external image URLs from crawler-triggered requests.
    _draw_og_icon(draw, 145, 332, 190, metadata, muted_white)
    _draw_og_icon(draw, OG_IMAGE_WIDTH - 145, 332, 190, metadata, muted_white)

    draw.ellipse(
        (icon_center_x - 60, icon_center_y - 60, icon_center_x + 60, icon_center_y + 60),
        fill=(255, 255, 255, 38),
        outline=(255, 255, 255, 105),
        width=3,
    )
    _draw_og_icon(draw, icon_center_x, icon_center_y, 82, metadata, white)

    title_lines = _wrap_text(draw, str(metadata.get("title") or DEFAULT_CHAT_TITLE), title_font, 900, 2)
    y = 220
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        draw.text(((OG_IMAGE_WIDTH - (bbox[2] - bbox[0])) / 2, y), line, fill=white, font=title_font)
        y += 88

    summary_lines = _wrap_text(draw, str(metadata.get("description") or DEFAULT_CHAT_DESCRIPTION), summary_font, 820, 3)
    y += 18
    for line in summary_lines:
        bbox = draw.textbbox((0, 0), line, font=summary_font)
        draw.text(((OG_IMAGE_WIDTH - (bbox[2] - bbox[0])) / 2, y), line, fill=soft_white, font=summary_font)
        y += 48

    draw.text((54, OG_IMAGE_HEIGHT - 68), "OpenMates", fill=white, font=brand_font)
    image = Image.alpha_composite(image, overlay)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


@router.post("/short-url", response_model=CreateShortUrlResponse)
@limiter.limit("10/hour")  # Stricter rate limit for creation (per user via auth)
async def create_short_url(
    request: Request,
    payload: CreateShortUrlRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Create a durable short URL entry.

    The client generates a token and shortKey, encrypts the full share URL with
    a key derived from shortKey via PBKDF2, and sends only the token + encrypted
    blob to this endpoint. The server stores the opaque blob in Directus.

    Requires authentication to prevent abuse.

    Security:
    - Rate limited to 10/hour per user
    - Token validated as 6-12 alphanumeric chars
    - Encrypted URL blob max 4KB
    - Optional TTL up to the share-key maximum; null means no expiration
    """
    try:
        # Validate token format
        if not SHORT_URL_TOKEN_PATTERN.match(payload.token):
            raise HTTPException(
                status_code=400,
                detail="Invalid token format: must be 6-12 alphanumeric characters",
            )

        # Validate blob size
        if len(payload.encrypted_url) > SHORT_URL_MAX_BLOB_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Encrypted URL too large: max {SHORT_URL_MAX_BLOB_SIZE} characters",
            )

        existing = await _get_short_link_record(payload.token, directus_service)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Token already in use. Please generate a new one.",
            )

        hashed_user_id = await _verify_short_link_target(payload, current_user, directus_service)
        now = int(time.time())
        expires_at = now + payload.ttl_seconds if payload.ttl_seconds else None
        try:
            await _create_directus_item(
                directus_service,
                SHORT_URL_COLLECTION,
                {
                    "token": payload.token,
                    "encrypted_url": payload.encrypted_url,
                    "content_type": payload.content_type,
                    "content_id": payload.content_id,
                    "hashed_user_id": hashed_user_id,
                    "password_protected": payload.password_protected,
                    "expires_at": expires_at,
                    "revoked_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except ShortUrlStorageUnavailable as exc:
            logger.warning(
                "Durable short URL storage unavailable; using cache fallback for token=%s: %s",
                payload.token,
                exc,
            )
            expires_at = await _store_short_url_cache_fallback(payload, cache_service, now)
        logger.info(
            "Short URL created: token=%s, content_type=%s, content_id=%s, expires_at=%s, user=%s",
            payload.token,
            payload.content_type,
            payload.content_id,
            expires_at,
            current_user.id,
        )

        return {"success": True, "expires_at": expires_at}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating short URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create short URL")


@router.get("/short-url/{token}", response_model=ResolveShortUrlResponse)
@limiter.limit("30/minute")  # Per-IP rate limit for resolution
async def resolve_short_url(
    request: Request,
    token: str,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Resolve a durable short URL.

    Returns the encrypted blob for a given token. The client decrypts it using
    the shortKey from the URL fragment (never sent to server).

    No authentication required — anyone with the token can resolve it.

    Security:
    - Rate limited to 30/minute per IP
    - Token validated as 6-12 alphanumeric chars
    """
    try:
        # Validate token format
        if not SHORT_URL_TOKEN_PATTERN.match(token):
            raise HTTPException(status_code=404, detail="Not found")

        record = await _get_short_link_record(token, directus_service)
        if record and not _short_link_is_expired_or_revoked(record):
            return {"encrypted_url": record["encrypted_url"]}

        # Legacy fallback for old Redis-backed /s/#token-shortKey links created
        # before durable short links moved the token into the path.
        if cache_service and hasattr(cache_service, "resolve_short_url"):
            from backend.core.api.app.services import cache_config
            current_count = await cache_service.get_resolve_count(token)
            if current_count >= cache_config.MAX_SHORT_URL_RESOLVES:
                raise HTTPException(status_code=429, detail="This short link has been used too many times and is now disabled.")
            encrypted_url = await cache_service.resolve_short_url(token)
            if encrypted_url is not None:
                await cache_service.increment_resolve_count(token)
                return {"encrypted_url": encrypted_url}

        raise HTTPException(status_code=404, detail="Short link expired or not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving short URL token={token}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")


@router.get("/short-url/{token}/metadata")
@limiter.limit("60/minute")
async def get_short_url_metadata(
    request: Request,
    token: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> Dict[str, Any]:
    """Return crawler-safe metadata for a durable short link."""
    return await _build_short_url_metadata(token, directus_service, encryption_service)


@router.get("/short-url/{token}/og-image.png")
@limiter.limit("60/minute")
async def get_short_url_og_image(
    request: Request,
    token: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> Response:
    """Generate a PNG social preview image for a durable short-link token."""
    metadata = await _build_short_url_metadata(token, directus_service, encryption_service)
    png = _render_short_url_og_png(metadata)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
