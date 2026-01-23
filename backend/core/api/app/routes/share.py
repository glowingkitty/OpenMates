# backend/core/api/app/routes/share.py
#
# REST API endpoints for share chat functionality
# Handles public access to shared chats and OG metadata updates

import logging
import hashlib
import time
import os
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.cache import CacheService
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
    share_with_community: Optional[bool] = None  # Whether the chat is shared with the community
    # For community sharing: client sends decrypted messages and embeds (zero-knowledge architecture)
    decrypted_messages: Optional[List[Dict[str, Any]]] = None  # [{role, content, created_at}]
    decrypted_embeds: Optional[List[Dict[str, Any]]] = None  # [{embed_id, type, content, created_at}]

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
            "encrypted_icon": chat.get("encrypted_icon"),  # Icon name encrypted with chat key
            "encrypted_category": chat.get("encrypted_category"),  # Category name encrypted with chat key
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
                logger.info(f"Decrypted title for chat {chat_id}: {title[:50]}...")
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
                logger.info(f"Decrypted summary for chat {chat_id}: {description[:50]}...")
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
        
        # Update sharing status: set is_shared=true and is_private=false when sharing
        if payload.is_shared is not None:
            updates["is_shared"] = payload.is_shared
            # When sharing (is_shared=true), ensure is_private=false
            if payload.is_shared:
                updates["is_private"] = False

        # Update community sharing preference
        if payload.share_with_community is not None:
            updates["share_with_community"] = payload.share_with_community
        
        # Note: When sharing with community, the client decrypts messages/embeds locally
        # and sends plaintext to the server (zero-knowledge architecture).
        # The share_link with encryption key is NOT sent to the server.
        # The server creates a separate demo_chats entry encrypted with Vault.
        
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
                'fields': 'id,shared_encrypted_title,shared_encrypted_summary,shared_encrypted_category,shared_encrypted_icon,shared_encrypted_follow_up_suggestions,is_shared,is_private'
            }
            updated_item = await directus_service.update_item("chats", chat_id, updates, params=params)
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
                    updated_chat = await directus_service.chat.get_chat_metadata(chat_id)
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
                    
                    # Log the actual field values (truncated) to see if they're there but empty
                    if updated_chat.get("shared_encrypted_title"):
                        title_preview = str(updated_chat.get("shared_encrypted_title"))[:50]
                        logger.debug(f"shared_encrypted_title value (first 50 chars): {title_preview}...")
                    else:
                        logger.warning(f"shared_encrypted_title is missing or empty for chat {chat_id}")
                    
                    if updated_chat.get("shared_encrypted_summary"):
                        summary_preview = str(updated_chat.get("shared_encrypted_summary"))[:50]
                        logger.debug(f"shared_encrypted_summary value (first 50 chars): {summary_preview}...")
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
        
        # If chat is shared with community, create a pending demo_chat entry with messages/embeds
        # Zero-knowledge architecture: Client decrypts and sends plaintext, server stores encrypted with Vault
        if payload.share_with_community and payload.decrypted_messages:
            demo_chat_id = None
            try:
                # Create a pending demo_chat entry with status='pending_approval'
                # Store messages and embeds encrypted with Vault (not the user's chat key)
                demo_chat = await directus_service.demo_chat.create_pending_demo_chat_with_content(
                    chat_id=chat_id,
                    title=payload.title,
                    summary=payload.summary,
                    category=payload.category,
                    icon=payload.icon,
                    follow_up_suggestions=payload.follow_up_suggestions,
                    decrypted_messages=payload.decrypted_messages,  # [{role, content, created_at}]
                    decrypted_embeds=payload.decrypted_embeds or []  # [{embed_id, type, content, created_at}]
                )
                if demo_chat:
                    demo_chat_id = demo_chat.get("id")  # UUID, not demo_id string
                    logger.info(f"Created pending demo chat {demo_chat_id} for community-shared chat {chat_id}")
                else:
                    logger.warning(f"Failed to create pending demo chat for chat {chat_id}")
            except Exception as e:
                # Log error but don't fail the request - demo chat creation is secondary
                logger.error(f"Failed to create pending demo chat for chat {chat_id}: {e}", exc_info=True)
            
            # Send notification email to admin
            try:
                admin_email = os.getenv("ADMIN_NOTIFY_EMAIL", "notify@openmates.org")
                
                # Dispatch email task to notify admin about community share
                from backend.core.api.app.tasks.celery_config import app
                app.send_task(
                    name='app.tasks.email_tasks.community_share_email_task.send_community_share_notification',
                    kwargs={
                        "admin_email": admin_email,
                        "chat_title": payload.title or "Untitled Chat",
                        "chat_summary": payload.summary or "",
                        "category": payload.category,
                        "icon": payload.icon,
                        "chat_id": chat_id,
                        "demo_chat_id": demo_chat_id  # UUID of the demo_chat entry
                    },
                    queue='email'
                )
                logger.info(f"Dispatched community share notification email task for chat {chat_id} to admin {admin_email}")
            except Exception as e:
                # Log error but don't fail the request if email dispatch fails
                logger.error(f"Failed to dispatch community share notification email for chat {chat_id}: {e}", exc_info=True)
        
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
            return {"embed": dummy_data, "child_embeds": [], "embed_keys": []}

        # Check if embed is private (not shared)
        # Use is_private field (mirrors chat sharing structure)
        # Default to False (shareable) if field doesn't exist (for backward compatibility)
        is_private = embed.get("is_private", False)
        if is_private:
            # Embed is private (unshared) - return dummy data
            logger.debug(f"Embed {embed_id} is private (unshared), returning dummy data")
            dummy_data = generate_dummy_encrypted_embed_data(embed_id)
            dummy_data.pop("is_dummy", None)
            return {"embed": dummy_data, "child_embeds": [], "embed_keys": []}

        # Embed exists and is shared - return real encrypted data
        logger.debug(f"Returning real encrypted data for shared embed {embed_id}")
        
        # Log the actual encrypted_content length to debug truncation issues
        encrypted_content = embed.get("encrypted_content")
        if encrypted_content:
            logger.debug(f"Embed {embed_id} encrypted_content length: {len(encrypted_content)} chars, preview: {encrypted_content[:50]}...")
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

        return {
            "embed": embed,
            "child_embeds": child_embeds,
            "embed_keys": embed_keys
        }

    except Exception as e:
        logger.error(f"Error fetching shared embed {embed_id}: {e}", exc_info=True)
        # On error, return dummy data to prevent information leakage
        dummy_data = generate_dummy_encrypted_embed_data(embed_id)
        dummy_data.pop("is_dummy", None)
        return {"embed": dummy_data, "child_embeds": [], "embed_keys": []}

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
                logger.info(f"Decrypted title for embed {embed_id}: {title[:50]}...")
            except Exception as e:
                logger.warning(f"Failed to decrypt shared_encrypted_title for embed {embed_id}: {e}")

        # Decrypt description if available
        if shared_encrypted_description:
            try:
                description = await encryption_service.decrypt(
                    shared_encrypted_description,
                    key_name="shared-content-metadata"
                )
                logger.info(f"Decrypted description for embed {embed_id}: {description[:50]}...")
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

