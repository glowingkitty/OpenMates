# backend/core/api/app/routes/share.py
# 
# REST API endpoints for share chat functionality
# Handles public access to shared chats and OG metadata updates

import logging
import hashlib
import time
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Body
from pydantic import BaseModel
from slowapi.util import get_remote_address

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.cache import CacheService

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
    is_shared: Optional[bool] = None  # Whether the chat is being shared (set to true when share link is created)

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

# --- Endpoints ---

@router.get("/chat/{chat_id}")
async def get_shared_chat(
    chat_id: str,
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get encrypted chat data for a shared chat.
    
    Returns:
    - Real encrypted data if chat exists and is_private = false
    - Dummy encrypted data if chat doesn't exist or is_private = true
      (prevents enumeration attacks)
    
    Security:
    - Rate limited to prevent brute force (TODO: apply via middleware or decorator)
    - Returns consistent dummy data for non-existent chats
    - Only returns real data if is_private = false
    """
    try:
        # Fetch chat from database
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        
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
        
        # Chat exists and is shared - return real encrypted data
        # Note: We return encrypted data as-is (client-side decryption)
        # The encryption key is in the URL fragment, never sent to server
        logger.debug(f"Returning real encrypted data for shared chat {chat_id}")
        
        # Get messages for the chat (encrypted, as stored in database)
        messages = await directus_service.chat.get_all_messages_for_chat(
            chat_id=chat_id,
            decrypt_content=False  # Return encrypted messages
        )
        
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
        
        return {
            "chat_id": chat_id,
            "encrypted_title": chat.get("encrypted_title"),
            "encrypted_chat_summary": chat.get("encrypted_chat_summary"),
            "encrypted_follow_up_request_suggestions": chat.get("encrypted_follow_up_request_suggestions"),
            "messages": messages or [],
            "embeds": embeds or [],
            "embed_keys": embed_keys or [],
            "is_dummy": False  # Internal flag, not sent to client
        }
        
    except Exception as e:
        logger.error(f"Error fetching shared chat {chat_id}: {e}", exc_info=True)
        # On error, return dummy data to prevent information leakage
        dummy_data = generate_dummy_encrypted_data(chat_id)
        dummy_data.pop("is_dummy", None)
        return dummy_data

@router.post("/chat/metadata")
async def update_share_metadata(
    payload: ShareChatMetadataUpdate,
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> Dict[str, Any]:
    """
    Update OG metadata for a shared chat.
    
    This endpoint is called when a user shares a chat to update the
    shared_encrypted_title and shared_encrypted_summary fields.
    
    The metadata is encrypted with the shared vault key (shared-content-metadata)
    so the server can decrypt it for OG tag generation without user context.
    """
    try:
        chat_id = payload.chat_id
        
        # Verify chat exists and user has permission (should be owner)
        # TODO: Add authentication check to ensure user owns the chat
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        
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
        
        # Update sharing status: set is_shared=true and is_private=false when sharing
        if payload.is_shared is not None:
            updates["is_shared"] = payload.is_shared
            # When sharing (is_shared=true), ensure is_private=false
            if payload.is_shared:
                updates["is_private"] = False
        
        # Update chat in database
        if updates:
            await directus_service.update_item("chats", chat_id, updates)
            logger.info(f"Updated OG metadata and sharing status for chat {chat_id}")
        
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
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Unshare a chat by setting is_private = true.
    
    This also clears shared_encrypted_title and shared_encrypted_summary
    to remove OG metadata.
    """
    try:
        chat_id = payload.chat_id
        
        # Verify chat exists and user has permission (should be owner)
        # TODO: Add authentication check to ensure user owns the chat
        chat = await directus_service.chat.get_chat_metadata(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Set is_private = true, is_shared = false, and clear shared metadata
        updates = {
            "is_private": True,
            "is_shared": False,
            "shared_encrypted_title": None,
            "shared_encrypted_summary": None
        }
        
        await directus_service.update_item("chats", chat_id, updates)
        logger.info(f"Unshared chat {chat_id}")
        
        return {"success": True, "chat_id": chat_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsharing chat {payload.chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unshare chat")

@router.get("/time")
async def get_server_time(request: Request) -> Dict[str, Any]:
    """
    Get current server time in Unix timestamp (seconds).
    
    Used for expiration validation of share links.
    """
    return {
        "timestamp": int(time.time()),
        "server_time": int(time.time())
    }

