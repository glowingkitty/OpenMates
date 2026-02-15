# backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py
#
# SECURITY: This module includes ASCII smuggling protection via the text_sanitization module.
# ASCII smuggling attacks use invisible Unicode characters to embed hidden instructions
# that bypass prompt injection detection but are processed by LLMs.
# See: docs/architecture/prompt_injection_protection.md

import logging
import json
import hashlib # Import hashlib for hashing user_id
import uuid
import time # Import time for performance timing
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import httpx

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService # Keep if directus_service is used by Celery tasks or future direct calls
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.schemas.chat import MessageInCache, AIHistoryMessage
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as AskSkillRequestSchema

# Import comprehensive ASCII smuggling sanitization
# This module protects against invisible Unicode characters used to embed hidden instructions
from backend.core.api.app.utils.text_sanitization import sanitize_text_for_ascii_smuggling

logger = logging.getLogger(__name__)


async def handle_message_received( # Renamed from handle_new_message, logic moved here
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Passed but might only be used by Celery task
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any] # Expected: {"chat_id": "...", "message": {"message_id": ..., "sender": ..., "content": ..., "timestamp": ...}}
):
    """
    Handles a new message sent from the client (now via "chat_message_added" type).
    1. Validates payload.
    2. Saves the message to cache.
    3. Encrypts content for persistence.
    4. Sends a task to Celery to persist to Directus.
    5. Sends confirmation to the originating client device.
    6. Broadcasts the new message to other connected devices of the same user.
    """
    # Performance timing: Track total processing time
    handler_start_time = time.time()
    # Extract message_id safely for logging (before message_payload_from_client is assigned)
    message_payload_temp = payload.get("message")
    message_id_for_log = message_payload_temp.get("message_id") if isinstance(message_payload_temp, dict) else "unknown"
    logger.info(f"[PERF] Message handler started for chat_id={payload.get('chat_id')}, message_id={message_id_for_log}")
    
    try:
        chat_id = payload.get("chat_id")
        # The client sends the message details within a "message" sub-dictionary in the payload
        message_payload_from_client = payload.get("message")
        # Get encrypted chat key for server storage (zero-knowledge architecture)
        encrypted_chat_key_from_client = payload.get("encrypted_chat_key")
        # Check if this is an incognito chat
        is_incognito = payload.get("is_incognito", False)

        if not chat_id or not message_payload_from_client or not isinstance(message_payload_from_client, dict):
            logger.error(f"Invalid message payload structure from {user_id}/{device_fingerprint_hash}: {payload}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Invalid message payload structure"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # CRITICAL: For incognito chats, skip Directus operations (no persistence, no ownership checks)
        # Incognito chats are not stored in Directus and should not be synced to other devices
        # Store chat_metadata for later use in determining if chat is existing (for history requests)
        chat_metadata_from_db: Optional[Dict[str, Any]] = None
        if not is_incognito:
            # CRITICAL: Verify chat ownership before processing message
            # This prevents authenticated users from sending messages to shared chats they don't own
            # For now, shared chats are read-only for non-owners (group chat support will be added later)
            try:
                chat_metadata_from_db = await directus_service.chat.get_chat_metadata(chat_id)
                if chat_metadata_from_db:
                    # Check if user owns this chat
                    is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
                    if not is_owner:
                        logger.warning(
                            f"User {user_id} attempted to send message to chat {chat_id} they don't own. "
                            f"Rejecting message (read-only shared chat)."
                        )
                        await manager.send_personal_message(
                            {
                                "type": "error",
                                "payload": {
                                    "message": "You cannot send messages to this shared chat. Shared chats are read-only for non-owners.",
                                    "chat_id": chat_id,
                                    "message_id": message_payload_from_client.get("message_id")
                                }
                            },
                            user_id,
                            device_fingerprint_hash
                        )
                        return
                else:
                    # Chat doesn't exist - this might be a new chat creation, which is allowed
                    logger.debug(f"Chat {chat_id} not found in database - treating as new chat creation")
            except Exception as e_ownership:
                logger.error(f"Error checking chat ownership for chat {chat_id}, user {user_id}: {e_ownership}", exc_info=True)
                # On error, reject the message for security (fail closed)
                await manager.send_personal_message(
                    {
                        "type": "error",
                        "payload": {
                            "message": "Unable to verify chat ownership. Please try again.",
                            "chat_id": chat_id,
                            "message_id": message_payload_from_client.get("message_id")
                        }
                    },
                    user_id,
                    device_fingerprint_hash
                )
                return
        else:
            logger.info(f"Processing incognito chat message {message_payload_from_client.get('message_id')} for chat {chat_id} - skipping Directus operations")

        message_id = message_payload_from_client.get("message_id")
        role = message_payload_from_client.get("role") 
        content_plain_raw = message_payload_from_client.get("content") # Markdown content for AI processing (raw, unsanitized)
        created_at = message_payload_from_client.get("created_at") # Unix timestamp (int/float)
        # Get chat_has_title flag early (indicates if this is first message or follow-up)
        # This is used to determine if we should request history (only for existing chats, not new ones)
        chat_has_title_from_client = message_payload_from_client.get("chat_has_title", False)
        
        # SECURITY: Sanitize content to protect against ASCII smuggling attacks
        # ASCII smuggling uses invisible Unicode characters to embed hidden instructions
        # that bypass prompt injection detection but are processed by LLMs.
        # This sanitization runs BEFORE any processing or storage of user content.
        # See: docs/architecture/prompt_injection_protection.md
        log_prefix_for_sanitization = f"[Chat {chat_id}][Msg {message_id}] "
        if isinstance(content_plain_raw, str) and content_plain_raw:
            content_plain, sanitization_stats = sanitize_text_for_ascii_smuggling(
                content_plain_raw,
                log_prefix=log_prefix_for_sanitization,
                include_stats=True
            )
            
            # Log security alert if hidden content was detected (potential attack)
            if sanitization_stats.get("hidden_ascii_detected"):
                logger.warning(
                    f"{log_prefix_for_sanitization}[SECURITY ALERT] ASCII smuggling attack detected! "
                    f"Removed {sanitization_stats['removed_count']} invisible characters from user message. "
                    f"Unicode Tags: {sanitization_stats['unicode_tags_count']}, "
                    f"Zero-Width: {sanitization_stats['zero_width_count']}, "
                    f"BiDi Controls: {sanitization_stats['bidi_control_count']}"
                )
            elif sanitization_stats.get("removed_count", 0) > 0:
                logger.info(
                    f"{log_prefix_for_sanitization}[ASCII SANITIZATION] "
                    f"Removed {sanitization_stats['removed_count']} invisible characters from user message"
                )
        else:
            content_plain = content_plain_raw
        
        # Determine if this is an existing chat by checking Directus messages_v
        # This is more reliable than client-provided chat_has_title, especially after server restarts
        is_existing_chat = False
        if chat_metadata_from_db:
            messages_v_from_db = chat_metadata_from_db.get("messages_v", 0)
            is_existing_chat = messages_v_from_db > 1  # > 1 means there are previous messages
            logger.debug(f"Chat {chat_id} messages_v from DB: {messages_v_from_db}, is_existing_chat: {is_existing_chat}")
        else:
            # Fallback to client-provided flag if DB check failed
            is_existing_chat = chat_has_title_from_client
            logger.debug(f"Chat {chat_id} not found in DB, using client flag chat_has_title: {chat_has_title_from_client}")

        # Validate required fields
        if not message_id or not role or content_plain is None or not created_at:
            logger.error(f"Missing fields in message data from {user_id}/{device_fingerprint_hash}: message_id={message_id}, role={role}, content_exists={content_plain is not None}, timestamp_exists={created_at is not None}")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing required fields (message_id, role, content, created_at) in message data"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # DELETE NEW CHAT SUGGESTION if user clicked one before sending this message
        # This ensures used suggestions are removed from the pool on both client and server
        # Skip for incognito chats (they don't use suggestions)
        encrypted_suggestion_to_delete = payload.get("encrypted_suggestion_to_delete")
        if encrypted_suggestion_to_delete and not is_incognito:
            logger.info(f"User {user_id} clicked a new chat suggestion, deleting it from server storage")
            try:
                # Hash user_id for database query
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                
                # First, query for the suggestion to get its ID
                query_params = {
                    'filter[hashed_user_id][_eq]': hashed_user_id,
                    'filter[encrypted_suggestion][_eq]': encrypted_suggestion_to_delete,
                    'fields': 'id',
                    'limit': 1
                }
                
                suggestions = await directus_service.get_items('new_chat_suggestions', params=query_params)
                
                if suggestions and len(suggestions) > 0:
                    suggestion_id = suggestions[0].get('id')
                    if suggestion_id:
                        # Delete the suggestion using its ID
                        delete_success = await directus_service.delete_item('new_chat_suggestions', suggestion_id)
                        
                        if delete_success:
                            logger.info(f"✅ Successfully deleted used new chat suggestion for user {user_id[:8]}... (ID: {suggestion_id})")
                            
                            # Invalidate the cache so next sync fetches updated suggestions
                            await cache_service.delete_new_chat_suggestions(hashed_user_id)
                            logger.debug(f"Invalidated new chat suggestions cache for user {user_id[:8]}...")
                        else:
                            logger.warning(f"Failed to delete suggestion {suggestion_id} for user {user_id[:8]}...")
                    else:
                        logger.warning(f"Suggestion found but no ID present for user {user_id[:8]}...")
                else:
                    logger.warning(f"No matching suggestion found to delete for user {user_id[:8]}...")
                    
            except Exception as e_suggestion_delete:
                logger.error(f"Failed to delete new chat suggestion for user {user_id}: {e_suggestion_delete}", exc_info=True)
                # Non-critical error - continue with message processing

        # Prepare message for cache (content remains plain for cache)
        # Ensure client_timestamp_unix is derived as an integer.
        client_timestamp_unix: int
        try:
            # Expecting created_at to be an int or float from the client.
            client_timestamp_unix = int(created_at)
        except (ValueError, TypeError) as e_ts:
            logger.warning(f"Invalid or missing timestamp from client (type: {type(created_at)}, value: {created_at}). Error: {e_ts}. Using current server time.")
            client_timestamp_unix = int(datetime.now(timezone.utc).timestamp())

        # Set default sender_name for user messages
        final_sender_name = "user" if role == "user" else "assistant"

        # SERVER-SIDE ENCRYPTION: Encrypt content with encryption_key_user_server (Vault)
        # This allows server to cache and access for AI while maintaining security
        # Get user's vault_key_id (try cache first, fallback to Directus)
        vault_key_start = time.time()
        user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
        
        if not user_vault_key_id:
            logger.debug(f"vault_key_id not in cache for user {user_id}, fetching from Directus")
            try:
                user_profile_result = await directus_service.get_user_profile(user_id)
                if not user_profile_result or not user_profile_result[0]:
                    logger.error(f"Failed to fetch user profile for encryption: {user_id}")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Failed to process message - user profile not found.", "chat_id": chat_id, "message_id": message_id}},
                        user_id, device_fingerprint_hash
                    )
                    return
                
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
                if not user_vault_key_id:
                    logger.error(f"User {user_id} missing vault_key_id in Directus profile")
                    await manager.send_personal_message(
                        {"type": "error", "payload": {"message": "Failed to process message - encryption key not found.", "chat_id": chat_id, "message_id": message_id}},
                        user_id, device_fingerprint_hash
                    )
                    return
                
                # Cache the vault_key_id for future use
                await cache_service.update_user(user_id, {"vault_key_id": user_vault_key_id})
                logger.debug(f"Cached vault_key_id for user {user_id}")
                    
            except Exception as e_profile:
                logger.error(f"Error fetching user profile for encryption: {e_profile}", exc_info=True)
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to process message - profile error.", "chat_id": chat_id, "message_id": message_id}},
                    user_id, device_fingerprint_hash
                )
                return
        
        vault_key_time = time.time() - vault_key_start
        logger.info(f"[PERF] Vault key retrieval took {vault_key_time:.3f}s for user {user_id}")
        
        if user_vault_key_id:
            logger.debug(f"Using cached vault_key_id for user {user_id}")
        
        # EXTRACT CODE BLOCKS FROM USER MESSAGE
        # ARCHITECTURE UPDATE: Client-side extraction is now preferred.
        # Modern clients extract code blocks before sending, replacing them with embed references.
        # Server-side extraction is kept as a FALLBACK for older clients.
        # 
        # Detection: If message contains embed references for code (```json with "type": "code"),
        # then client already did extraction and we skip server-side extraction.
        extracted_code_embeds: List[Dict[str, Any]] = []
        hashed_user_id_for_embeds = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Check if client already extracted code blocks (modern client)
        client_already_extracted = False
        if isinstance(content_plain, str):
            # Look for embed reference JSON blocks with type "code"
            if '"type": "code"' in content_plain or '"type":"code"' in content_plain:
                # Verify it's an embed reference, not just coincidental text
                import re
                embed_ref_pattern = r'```json\s*\n\s*\{\s*"type"\s*:\s*"code"\s*,\s*"embed_id"\s*:\s*"[^"]+"\s*\}'
                if re.search(embed_ref_pattern, content_plain):
                    client_already_extracted = True
                    logger.debug(f"Message {message_id} contains client-extracted code embed references - skipping server extraction")
        
        if not client_already_extracted and isinstance(content_plain, str) and '```' in content_plain:
            # FALLBACK: Server-side extraction for older clients
            # Content has potential code blocks that need extraction
            try:
                from backend.core.api.app.services.embed_service import EmbedService
                embed_service = EmbedService(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service
                )
                
                code_extract_start = time.time()
                content_plain, extracted_code_embeds = await embed_service.extract_code_blocks_from_user_message(
                    content=content_plain,
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=user_id,
                    user_id_hash=hashed_user_id_for_embeds,
                    user_vault_key_id=user_vault_key_id,
                    log_prefix=f"[Chat {chat_id}]"
                )
                code_extract_time = time.time() - code_extract_start
                
                if extracted_code_embeds:
                    logger.info(f"[PERF] Code block extraction took {code_extract_time:.3f}s, extracted {len(extracted_code_embeds)} embeds from user message {message_id}")
                    
            except Exception as e_code_extract:
                logger.error(f"Error extracting code blocks from user message {message_id}: {e_code_extract}", exc_info=True)
                # Non-critical error - continue with original content
        
        content_to_encrypt_str: str
        if isinstance(content_plain, dict):
            content_to_encrypt_str = json.dumps(content_plain)
        elif isinstance(content_plain, str):
            content_to_encrypt_str = content_plain
        else:
            logger.warning(f"Message content for chat {chat_id}, msg {message_id} is unexpected type {type(content_plain)}. Converting to string.")
            content_to_encrypt_str = str(content_plain)
        
        encrypt_start = time.time()
        try:
            # Encrypt with user-specific server key (encryption_key_user_server from Vault)
            encrypted_content_for_cache, _ = await encryption_service.encrypt_with_user_key(
                content_to_encrypt_str, 
                user_vault_key_id
            )
            encrypt_time = time.time() - encrypt_start
            logger.info(f"[PERF] Message encryption took {encrypt_time:.3f}s for message {message_id}")
            logger.debug(f"Encrypted message content for cache using user vault key: {user_vault_key_id}")
        except Exception as e_encrypt:
            logger.error(f"Failed to encrypt message content for cache: {e_encrypt}", exc_info=True)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to encrypt message for cache.", "chat_id": chat_id, "message_id": message_id}},
                user_id, device_fingerprint_hash
            )
            return

        # For incognito chats, skip cache operations (no server-side persistence)
        # Still need to track versions for client confirmation, but don't persist to cache
        if is_incognito:
            # For incognito chats, use dummy version numbers (not persisted)
            new_messages_v = 1  # Will be incremented by client
            new_last_edited_overall_timestamp = client_timestamp_unix
            logger.debug(f"Skipping cache save for incognito chat {chat_id} - no server-side persistence")
        else:
            message_for_cache = MessageInCache(
                id=message_id,
                chat_id=chat_id,
                role=role,
                category=None, # Not needed for Phase 1 AI processing
                sender_name=final_sender_name,
                encrypted_content=encrypted_content_for_cache,  # Server-side encrypted
                created_at=client_timestamp_unix,
                status="sending"
            )
            # Save to cache first
            # This also updates chat versions (messages_v, last_edited_overall_timestamp)
            # and returns the new versions.
            cache_save_start = time.time()
            version_update_result = await cache_service.save_chat_message_and_update_versions(
                user_id=user_id,
                chat_id=chat_id,
                message_data=message_for_cache
            )
            cache_save_time = time.time() - cache_save_start
            logger.info(f"[PERF] Cache save took {cache_save_time:.3f}s for message {message_id}")

            if not version_update_result:
                logger.error(f"Failed to save message {message_id} to cache or update versions for chat {chat_id}. User: {user_id}")
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to process message due to cache error.", "chat_id": chat_id, "message_id": message_id}},
                    user_id, device_fingerprint_hash
                )
                return
                
            new_messages_v = version_update_result["messages_v"]
            new_last_edited_overall_timestamp = version_update_result["last_edited_overall_timestamp"]
            
            logger.debug(f"Saved encrypted message {message_id} to cache for chat {chat_id} by user {user_id}. New messages_v: {new_messages_v}")

        # DELETE DRAFT FROM CACHE when message is sent
        # This ensures draft is not restored on next login (zero-knowledge architecture)
        # The client will also send a delete_draft message, but we do it here preemptively
        # to avoid race conditions between message send and draft delete
        # Skip for incognito chats (drafts are not saved for incognito chats)
        if not is_incognito:
            try:
                cache_delete_success = await cache_service.delete_user_draft_from_cache(
                    user_id=user_id,
                    chat_id=chat_id
                )
                if cache_delete_success:
                    logger.info(f"Successfully deleted draft from cache for chat {chat_id} after message {message_id} was sent")
                else:
                    logger.debug(f"Draft cache key not found for chat {chat_id} (already deleted or never existed)")
                
                # Also delete the user-specific draft version from the general chat versions key
                version_delete_success = await cache_service.delete_user_draft_version_from_chat_versions(
                    user_id=user_id,
                    chat_id=chat_id
                )
                if version_delete_success:
                    logger.debug(f"Successfully deleted user-specific draft version from chat versions for chat {chat_id}")
                else:
                    logger.debug(f"Draft version not found in chat versions for chat {chat_id} (already deleted or never existed)")
                
                # CRITICAL FIX: ALWAYS broadcast draft deletion to other devices when a message is sent
                # This ensures consistent state across all user devices, even if the draft was never
                # stored on the server (e.g., server cache expired, or draft was only saved locally).
                # Other devices might have a locally cached draft that needs to be cleared.
                # Previously, this only broadcasted if cache_delete_success or version_delete_success,
                # which caused stale drafts to persist on other devices when the server had no draft to delete.
                try:
                    await manager.broadcast_to_user(
                        message={
                            "type": "draft_deleted",
                            "payload": {"chat_id": chat_id}
                        },
                        user_id=user_id,
                        exclude_device_hash=device_fingerprint_hash
                    )
                    logger.info(f"Broadcasted draft_deleted event for chat {chat_id} to other user devices after message send")
                except Exception as e_broadcast:
                    logger.warning(f"Failed to broadcast draft_deleted for chat {chat_id}: {e_broadcast}")
            except Exception as e_draft_delete:
                logger.warning(f"Error deleting draft from cache for chat {chat_id} after message send: {e_draft_delete}")
                # Non-critical error - draft will expire via TTL or be overwritten by client delete_draft message
        else:
            logger.debug(f"Skipping draft deletion for incognito chat {chat_id} - drafts are not saved for incognito chats")

        # ENCRYPTED MESSAGE FOR AI PROCESSING
        # This handler receives cleartext messages from client for AI inference
        # Content is encrypted with encryption_key_user_server before caching
        # NO PERMANENT STORAGE happens here - storage is handled by separate encrypted_chat_metadata handler
        
        # Validate that client is NOT sending encrypted content (wrong handler)
        if message_payload_from_client.get("encrypted_content"):
            logger.error("Client sent encrypted content to chat_message_added handler. This should go to encrypted_chat_metadata handler instead.")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Encrypted content should be sent to encrypted_chat_metadata endpoint"}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        logger.info(f"Processing cleartext message {message_id} for AI inference in chat {chat_id}. No storage in this handler.")
        logger.info(f"DEBUG: content_plain length: {len(content_plain) if content_plain else 0}, chat_has_title: {chat_has_title_from_client}")
        
        # Process embeds if provided by client
        # Embeds are sent as cleartext (TOON-encoded) and will be encrypted server-side for cache
        embeds_from_client = payload.get("embeds", [])
        if embeds_from_client:
            logger.info(f"Processing {len(embeds_from_client)} embeds from client for message {message_id}")
            
            # Import embed service
            from backend.core.api.app.services.embed_service import EmbedService
            embed_service = EmbedService(
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service
            )
            
            # Hash IDs for privacy (zero-knowledge architecture)
            hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            
            # Process each embed
            for embed_data in embeds_from_client:
                try:
                    embed_id = embed_data.get("embed_id")
                    embed_type = embed_data.get("type")  # Decrypted type from client
                    embed_content = embed_data.get("content")  # TOON-encoded string
                    embed_status = embed_data.get("status", "finished")
                    embed_text_preview = embed_data.get("text_preview")
                    embed_ids = embed_data.get("embed_ids")  # For composite embeds
                    
                    if not embed_id or not embed_type or not embed_content:
                        logger.warning("Invalid embed data from client: missing required fields")
                        continue
                    
                    # Encrypt embed content with vault key for server cache
                    # Server can decrypt for AI context building
                    # encrypt_with_user_key returns (ciphertext, key_version) tuple
                    encrypted_content, _ = await encryption_service.encrypt_with_user_key(
                        plaintext=embed_content,
                        key_id=user_vault_key_id
                    )
                    
                    # Encrypt embed type for zero-knowledge storage
                    encrypted_type, _ = await encryption_service.encrypt_with_user_key(
                        plaintext=embed_type,
                        key_id=user_vault_key_id
                    )
                    
                    # Encrypt text preview if provided
                    encrypted_text_preview = None
                    if embed_text_preview:
                        encrypted_text_preview, _ = await encryption_service.encrypt_with_user_key(
                            plaintext=embed_text_preview,
                            key_id=user_vault_key_id
                        )
                    
                    # Cache embed for AI processing
                    embed_cache_data = {
                        "embed_id": embed_id,
                        "encrypted_type": encrypted_type,
                        "encrypted_content": encrypted_content,
                        "encrypted_text_preview": encrypted_text_preview,
                        "status": embed_status,
                        "embed_ids": embed_ids,  # For composite embeds
                        "hashed_chat_id": hashed_chat_id,
                        "hashed_message_id": hashed_message_id,
                        "hashed_user_id": hashed_user_id,
                        "created_at": int(datetime.now(timezone.utc).timestamp()),
                        "updated_at": int(datetime.now(timezone.utc).timestamp())
                    }
                    
                    # Store in cache
                    # Note: embed_data is already vault-encrypted above
                    await cache_service.set_embed_in_cache(
                        embed_id=embed_id,
                        embed_data=embed_cache_data,
                        chat_id=chat_id
                    )
                    
                    # Add to chat embed index
                    await cache_service.add_embed_id_to_chat_index(chat_id, embed_id)
                    
                    logger.debug(f"Cached embed {embed_id} (type: {embed_type}) for message {message_id}")
                    
                except Exception as e_embed:
                    logger.error(f"Error processing embed from client: {e_embed}", exc_info=True)
                    # Non-critical error - continue processing other embeds
        
        # ARCHITECTURE: Client-created embeds for Directus storage
        # Client sends BOTH cleartext (for AI cache above) AND client-encrypted version (for Directus)
        # in the same request. This avoids round-trip WebSocket calls (send_embed_data → store_embed).
        # The encrypted_embeds array contains pre-encrypted embeds ready for direct Directus storage.
        encrypted_embeds_from_client = payload.get("encrypted_embeds", [])
        if encrypted_embeds_from_client and not is_incognito:
            logger.info(f"Storing {len(encrypted_embeds_from_client)} client-encrypted embeds directly to Directus for message {message_id}")
            
            for encrypted_embed in encrypted_embeds_from_client:
                try:
                    embed_id = encrypted_embed.get("embed_id")
                    if not embed_id:
                        logger.warning("Encrypted embed missing embed_id, skipping")
                        continue
                    
                    # ARCHITECTURE: Fill in hashed_user_id if client didn't provide it
                    # This happens for new chats where the client doesn't have user_id yet.
                    # The server knows the user from the authenticated session, so we can fill it in.
                    if not encrypted_embed.get("hashed_user_id"):
                        encrypted_embed["hashed_user_id"] = hashed_user_id
                        logger.debug(f"Filled in hashed_user_id for embed {embed_id}")
                    
                    # Store client-encrypted embed directly in Directus
                    # This is the zero-knowledge architecture: server cannot decrypt this data
                    await directus_service.embed.create_embed(encrypted_embed)
                    logger.debug(f"Stored client-encrypted embed {embed_id} in Directus")
                    
                    # Also store embed keys if provided
                    # CRITICAL: embed_keys must be stored for the embed to be decryptable later
                    embed_keys = encrypted_embed.get("embed_keys", [])
                    if embed_keys:
                        logger.info(f"[EMBED_KEYS] 🔑 Received {len(embed_keys)} embed_key(s) for embed {embed_id}")
                        for key_entry in embed_keys:
                            # Fill in hashed_user_id for embed keys too if missing
                            if not key_entry.get("hashed_user_id"):
                                key_entry["hashed_user_id"] = hashed_user_id
                            
                            hashed_embed_id_preview = key_entry.get("hashed_embed_id", "")[:16]
                            key_type = key_entry.get("key_type")
                            
                            result = await directus_service.embed.create_embed_key(key_entry)
                            if result:
                                logger.info(f"[EMBED_KEYS] ✅ Stored embed_key for {embed_id}: hashed_embed_id={hashed_embed_id_preview}..., key_type={key_type}")
                            else:
                                logger.error(f"[EMBED_KEYS] ❌ Failed to store embed_key for {embed_id}: hashed_embed_id={hashed_embed_id_preview}..., key_type={key_type}")
                        logger.info(f"[EMBED_KEYS] Completed storing {len(embed_keys)} embed key(s) for embed {embed_id}")
                    else:
                        logger.warning(f"[EMBED_KEYS] ⚠️ No embed_keys provided for embed {embed_id} - embed will not be decryptable!")
                    
                except Exception as e_store:
                    logger.error(f"Error storing client-encrypted embed {encrypted_embed.get('embed_id')}: {e_store}", exc_info=True)
                    # Non-critical error - continue with other embeds

        # Send confirmation to the originating client device
        confirmation_payload = {
            "type": "chat_message_confirmed", # Client expects this for their sent message
            "payload": {
                "chat_id": chat_id,
                "message_id": message_id,
                "temp_id": message_payload_from_client.get("temp_id"), # Echo back temp_id if client sent one
                "new_messages_v": new_messages_v,
                "new_last_edited_overall_timestamp": new_last_edited_overall_timestamp
            }
        }
        await manager.broadcast_to_user_specific_event(
            user_id=user_id,
            event_name=confirmation_payload["type"],
            payload=confirmation_payload["payload"]
        )
        logger.debug(f"Broadcasted chat_message_confirmed event for message {message_id} to user {user_id}")

        # SEND EXTRACTED CODE EMBEDS TO CLIENT
        # These embeds were extracted from code blocks in the user message
        # Client needs to encrypt and store them, then send back for Directus storage
        if extracted_code_embeds:
            current_timestamp = int(datetime.now(timezone.utc).timestamp())
            
            for embed_data in extracted_code_embeds:
                try:
                    # Send embed data to client for encryption and storage
                    # Using send_embed_data event type which client already handles
                    # Payload structure must match SendEmbedDataPayload type in frontend
                    await manager.send_personal_message(
                        message={
                            "type": "send_embed_data",
                            "event_for_client": "send_embed_data",
                            "payload": {
                                "embed_id": embed_data["embed_id"],
                                "type": embed_data["type"],  # "code" - plaintext for client to encrypt
                                "content": embed_data["content"],  # TOON-encoded string (cleartext for client to encrypt)
                                "status": embed_data["status"],
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "user_id": user_id,
                                "is_private": False,
                                "is_shared": False,
                                "createdAt": current_timestamp,
                                "updatedAt": current_timestamp,
                                "file_path": embed_data.get("filename"),  # filename maps to file_path
                                "text_length_chars": len(embed_data.get("content", ""))
                            }
                        },
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash
                    )
                    logger.debug(f"Sent code embed {embed_data['embed_id']} to client for encrypted storage")
                    
                    # Also cache the embed server-side with vault encryption for AI processing
                    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
                    hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
                    
                    # Encrypt embed content with vault key for server cache
                    # encrypt_with_user_key returns (ciphertext, key_version) tuple
                    encrypted_embed_content, _ = await encryption_service.encrypt_with_user_key(
                        plaintext=embed_data["content"],
                        key_id=user_vault_key_id
                    )
                    encrypted_embed_type, _ = await encryption_service.encrypt_with_user_key(
                        plaintext=embed_data["type"],
                        key_id=user_vault_key_id
                    )
                    
                    embed_cache_data = {
                        "embed_id": embed_data["embed_id"],
                        "encrypted_type": encrypted_embed_type,
                        "encrypted_content": encrypted_embed_content,
                        "status": embed_data["status"],
                        "hashed_chat_id": hashed_chat_id,
                        "hashed_message_id": hashed_message_id,
                        "hashed_user_id": hashed_user_id_for_embeds,
                        "created_at": int(datetime.now(timezone.utc).timestamp()),
                        "updated_at": int(datetime.now(timezone.utc).timestamp())
                    }
                    
                    await cache_service.set_embed_in_cache(
                        embed_id=embed_data["embed_id"],
                        embed_data=embed_cache_data,
                        user_vault_key_id=user_vault_key_id
                    )
                    await cache_service.add_embed_id_to_chat_index(chat_id, embed_data["embed_id"])
                    
                    logger.debug(f"Cached code embed {embed_data['embed_id']} for AI processing")
                    
                except Exception as e_embed_send:
                    logger.error(f"Error sending/caching code embed {embed_data.get('embed_id')}: {e_embed_send}", exc_info=True)
                    # Non-critical error - continue with other embeds
            
            logger.info(f"Sent {len(extracted_code_embeds)} code embeds to client for message {message_id}")

        # CRITICAL: For incognito chats, DO NOT broadcast to other devices
        # Incognito chats are device-specific and should not be synced
        if not is_incognito:
            # Fetch encrypted_chat_key for device sync if not provided by client
            # This is critical for zero-knowledge architecture across multiple devices
            encrypted_chat_key_for_broadcast = encrypted_chat_key_from_client
            if not encrypted_chat_key_for_broadcast:
                try:
                    # Try to get from cache first (faster)
                    chat_metadata_cache = await cache_service.get_chat_list_item_data(user_id, chat_id)
                    if chat_metadata_cache and hasattr(chat_metadata_cache, 'encrypted_chat_key'):
                        encrypted_chat_key_for_broadcast = chat_metadata_cache.encrypted_chat_key
                        logger.debug(f"Retrieved encrypted_chat_key from cache for chat {chat_id}")
                    
                    # Fallback to database if not in cache
                    if not encrypted_chat_key_for_broadcast:
                        chat_metadata_db = await directus_service.chat.get_chat_metadata(chat_id)
                        if chat_metadata_db and chat_metadata_db.get('encrypted_chat_key'):
                            encrypted_chat_key_for_broadcast = chat_metadata_db['encrypted_chat_key']
                            logger.debug(f"Retrieved encrypted_chat_key from database for chat {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to retrieve encrypted_chat_key for chat {chat_id}: {e}")
            
            # Broadcast the new message to other connected devices of the same user
            broadcast_payload_content = {
                "type": "new_chat_message", # A distinct type for other clients receiving a new message
                "payload": {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "role": role,
                    "sender_name": final_sender_name,
                    "content": content_plain,
                    "created_at": client_timestamp_unix,
                    "messages_v": new_messages_v,
                    "last_edited_overall_timestamp": new_last_edited_overall_timestamp,
                    "encrypted_chat_key": encrypted_chat_key_for_broadcast  # Critical for device sync
                    # Add any other fields clients expect for a new message display
                }
            }
            await manager.broadcast_to_user(
                message=broadcast_payload_content,
                user_id=user_id,
                exclude_device_hash=device_fingerprint_hash # Exclude the sender's device
            )
            logger.debug(f"Broadcasted new_chat_message for {message_id} to other devices of user {user_id} (encrypted_chat_key included: {bool(encrypted_chat_key_for_broadcast)})")
        else:
            logger.debug(f"Skipping broadcast for incognito chat {chat_id} - incognito chats are not synced to other devices")

        # --- BEGIN AI SKILL INVOCATION ---
        logger.debug(f"Preparing to invoke AI for chat {chat_id} after user message {message_id}")
        
        message_history_for_ai: List[AIHistoryMessage] = []
        
        # Check if client provided chat history (for cache miss or stale cache scenarios)
        # For incognito chats OR duplicated demo chats, client MUST provide full history
        # (no server-side caching for these new/temp chats)
        client_provided_history = payload.get("message_history") or message_payload_from_client.get("message_history")
        
        history_start = time.time()
        try:
            # For incognito or duplicated chats (new chats with history), require client to provide full history
            # Detection: if it's a new chat (not existing) but has history messages, it's a duplication
            is_duplication = not is_existing_chat and client_provided_history and len(client_provided_history) > 0
            
            if is_incognito or is_duplication:
                if not client_provided_history or not isinstance(client_provided_history, list):
                    logger.warning(f"Incognito/Duplicated chat {chat_id} missing message_history - requesting from client")
                    await manager.send_personal_message(
                        {
                            "type": "request_chat_history",
                            "payload": {
                                "chat_id": chat_id,
                                "reason": "temp_chat_requires_history",
                                "message": "Incognito or duplicated chats require full message history with each request"
                            }
                        },
                        user_id,
                        device_fingerprint_hash
                    )
                    return  # Stop processing until client provides history
                logger.info(f"Using client-provided history for temp chat {chat_id} (incognito={is_incognito}, duplication={is_duplication}): {len(client_provided_history)} messages")
            
            if client_provided_history and isinstance(client_provided_history, list):
                # Client provided full history - use it directly and re-cache
                logger.info(f"Client provided {len(client_provided_history)} messages for chat {chat_id}. Using client history and re-caching.")
                
                # Clear old cache and re-cache with current vault key
                await cache_service.delete_chat_messages_history(user_id, chat_id)
                
                for hist_msg in client_provided_history:
                    # CRITICAL: Resolve embed references in message content before adding to AI history
                    # According to embeds architecture, messages contain embed references (JSON blocks)
                    # that need to be replaced with actual embed content for LLM context
                    hist_content = hist_msg.get("content", "")
                    resolved_hist_content = hist_content
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        resolved_hist_content = await embed_service.resolve_embed_references_in_content(
                            content=hist_content,
                            user_vault_key_id=user_vault_key_id,
                            log_prefix=f"[Chat {chat_id}]"
                        )
                    except Exception as e_resolve:
                        logger.warning(f"Failed to resolve embed references in client-provided message for chat {chat_id}: {e_resolve}. Using original content.")
                        # Continue with original content if resolution fails
                    
                    # Add to AI history
                    message_history_for_ai.append(
                        AIHistoryMessage(
                            role=hist_msg.get("role", "user"),
                            category=hist_msg.get("category"),
                            sender_name=hist_msg.get("sender_name", "user"),
                            content=resolved_hist_content, # Resolved content with embeds replaced
                            created_at=int(hist_msg.get("created_at", datetime.now(timezone.utc).timestamp()))
                        )
                    )
                    
                    # Re-encrypt and cache for future use
                    try:
                        content_str = hist_msg.get("content", "")
                        if isinstance(content_str, dict):
                            content_str = json.dumps(content_str)
                        
                        encrypted_hist_content, _ = await encryption_service.encrypt_with_user_key(
                            content_str,
                            user_vault_key_id
                        )
                        
                        cached_msg = MessageInCache(
                            id=hist_msg.get("message_id", str(uuid.uuid4())),
                            chat_id=chat_id,
                            role=hist_msg.get("role", "user"),
                            category=hist_msg.get("category"),
                            sender_name=hist_msg.get("sender_name", "user"),
                            encrypted_content=encrypted_hist_content,
                            created_at=int(hist_msg.get("created_at", datetime.now(timezone.utc).timestamp())),
                            status="delivered"
                        )
                        
                        await cache_service.add_message_to_chat_history(
                            user_id,
                            chat_id,
                            cached_msg.model_dump_json()
                        )
                    except Exception as e_recache:
                        logger.warning(f"Failed to re-cache message for chat {chat_id}: {e_recache}")
                
                logger.info(f"Re-cached {len(client_provided_history)} messages for chat {chat_id} with current vault key")
                
            else:
                # No client history - try AI inference cache
                # For incognito chats, skip cache (no server-side caching)
                if is_incognito:
                    logger.warning(f"Incognito chat {chat_id} missing message_history - cannot use cache")
                    await manager.send_personal_message(
                        {
                            "type": "request_chat_history",
                            "payload": {
                                "chat_id": chat_id,
                                "reason": "incognito_requires_history",
                                "message": "Incognito chats require full message history with each request"
                            }
                        },
                        user_id,
                        device_fingerprint_hash
                    )
                    return  # Stop processing until client provides history
                
                # 1. Fetch message history for the chat FROM AI CACHE ONLY (vault-encrypted)
                # AI cache contains encrypted_content (encrypted with encryption_key_user_server from Vault)
                # Server decrypts for AI processing, maintaining security
                cache_fetch_start = time.time()
                cached_messages_str_list = await cache_service.get_ai_messages_history(user_id, chat_id) # Fetches all vault-encrypted messages
                cache_fetch_time = time.time() - cache_fetch_start
                logger.info(f"[PERF] Cache fetch for AI history took {cache_fetch_time:.3f}s, found {len(cached_messages_str_list) if cached_messages_str_list else 0} messages")
                
                if cached_messages_str_list:
                    logger.info(f"Found {len(cached_messages_str_list)} encrypted messages in AI cache for chat {chat_id}. Loading in chronological order (oldest first).")
                    decryption_failures = 0
                    # CRITICAL: Cache stores newest first (LPUSH), so we reverse to get chronological order (oldest first)
                    # This ensures message history is in the correct order for AI processing
                    for msg_str in reversed(cached_messages_str_list):
                        try:
                            msg_cache_data = json.loads(msg_str)
                            
                            # Decrypt content using encryption_key_user_server (Vault)
                            encrypted_content = msg_cache_data.get("encrypted_content")
                            if not encrypted_content:
                                logger.debug(f"Cached message missing encrypted_content for chat {chat_id}, skipping for AI history")
                                continue
                            
                            try:
                                # Decrypt with user-specific server key
                                decrypted_content = await encryption_service.decrypt_with_user_key(
                                    encrypted_content,
                                    user_vault_key_id
                                )
                                
                                if not decrypted_content:
                                    logger.warning(f"Failed to decrypt cached message content for chat {chat_id} (vault_key: {user_vault_key_id[:20]}...), skipping")
                                    decryption_failures += 1
                                    continue
                                    
                            except Exception as e_decrypt:
                                logger.warning(f"Error decrypting cached message for AI history in chat {chat_id} (vault_key: {user_vault_key_id[:20]}...): {e_decrypt}")
                                decryption_failures += 1
                                continue
                        
                            # Determine role and category for history messages
                            history_role = msg_cache_data.get("role", "user" if msg_cache_data.get("sender_name") == final_sender_name else "assistant")
                            history_category = msg_cache_data.get("category")
                            history_sender_name = msg_cache_data.get("sender_name", "user" if history_role == "user" else "assistant")

                            # Ensure timestamp is an int
                            history_timestamp_val: int
                            try:
                                history_timestamp_val = int(msg_cache_data.get("created_at"))
                            except (ValueError, TypeError):
                                logger.warning(f"Cached message for chat {chat_id} has non-integer or missing timestamp '{msg_cache_data.get('created_at')}'. Defaulting to current time.")
                                history_timestamp_val = int(datetime.now(timezone.utc).timestamp())

                            # CRITICAL: Resolve embed references in message content before adding to AI history
                            # According to embeds architecture, messages contain embed references (JSON blocks)
                            # that need to be replaced with actual embed content for LLM context
                            resolved_content = decrypted_content
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(
                                    cache_service=cache_service,
                                    directus_service=directus_service,
                                    encryption_service=encryption_service
                                )
                                resolved_content = await embed_service.resolve_embed_references_in_content(
                                    content=decrypted_content,
                                    user_vault_key_id=user_vault_key_id,
                                    log_prefix=f"[Chat {chat_id}]"
                                )
                                # Log if any embed references were found but not resolved
                                if "```json" in decrypted_content and "```json" in resolved_content:
                                    logger.debug(
                                        f"[Chat {chat_id}] Some embed references may not have been resolved "
                                        f"(embeds may be missing from cache). Original content length: {len(decrypted_content)}, "
                                        f"resolved length: {len(resolved_content)}"
                                    )
                            except Exception as e_resolve:
                                logger.error(
                                    f"Failed to resolve embed references in message for chat {chat_id}: {e_resolve}. "
                                    f"Using original content. This may cause LLM context issues.",
                                    exc_info=True
                                )
                                # Continue with original content if resolution fails

                            message_history_for_ai.append(
                                AIHistoryMessage(
                                    role=history_role,
                                    category=history_category,
                                    sender_name=history_sender_name,
                                    content=resolved_content, # Resolved content with embeds replaced
                                    created_at=history_timestamp_val
                                )
                            )
                        except json.JSONDecodeError:
                            logger.warning(f"Could not parse cached message string for chat {chat_id}: {msg_str[:100]}...")
                        except Exception as e_hist_parse:
                            logger.warning(f"Error processing cached message for AI history: {e_hist_parse}")
                    
                    logger.info(
                        f"Successfully decrypted {len(message_history_for_ai)} messages from AI cache for chat {chat_id} "
                        f"(failures: {decryption_failures}/{len(cached_messages_str_list)}). "
                        f"Message roles: {[msg.role for msg in message_history_for_ai]}"
                    )
                    
                    # CRITICAL FIX: Validate chat history based on database messages_v vs cached messages
                    # For existing chats, we should have historical context beyond just the current message
                    messages_v_from_db = chat_metadata_from_db.get("messages_v", 0) if chat_metadata_from_db else 0
                    expected_total_messages = messages_v_from_db if messages_v_from_db > 0 else 1

                    # Count messages excluding the current message (which was just added to history at the end)
                    # Current message gets appended later, so history should have (expected - 1) previous messages
                    expected_previous_messages = max(0, expected_total_messages - 1)
                    actual_previous_messages = len(message_history_for_ai)

                    logger.debug(f"History validation for chat {chat_id}: expected_total={expected_total_messages}, expected_previous={expected_previous_messages}, actual_previous={actual_previous_messages}, decryption_failures={decryption_failures}")

                    # For existing chats with expected history, validate we have sufficient context
                    if is_existing_chat and expected_previous_messages > 0:
                        # Check if we have significantly fewer messages than expected
                        # Allow some tolerance for edge cases, but require at least 50% of expected messages
                        minimum_required = max(1, expected_previous_messages // 2)

                        if actual_previous_messages < minimum_required:
                            # Insufficient history for existing chat - request from client
                            logger.warning(f"Insufficient history for existing chat {chat_id}: expected {expected_previous_messages} previous messages, got {actual_previous_messages} (minimum required: {minimum_required}). Cache likely stale after server restart.")
                            await manager.send_personal_message(
                                {
                                    "type": "request_chat_history",
                                    "payload": {
                                        "chat_id": chat_id,
                                        "reason": "insufficient_cache_history",
                                        "message": "Server cache missing chat history. Please resend your message with full chat history included",
                                        "expected_messages": expected_total_messages,
                                        "cached_messages": actual_previous_messages
                                    }
                                },
                                user_id,
                                device_fingerprint_hash
                            )
                            return  # Stop processing until client provides history

                    # Legacy validation for complete cache failures
                    if len(message_history_for_ai) < 1:
                        if is_existing_chat:
                            # Existing chat with no history at all - request it
                            logger.warning(f"No messages successfully decrypted from cache for chat {chat_id} ({decryption_failures} decryption failures out of {len(cached_messages_str_list)} cached). Requesting full history from client.")
                            await manager.send_personal_message(
                                {
                                    "type": "request_chat_history",
                                    "payload": {
                                        "chat_id": chat_id,
                                        "reason": "cache_miss" if len(cached_messages_str_list) == 0 else "decryption_failed",
                                        "message": "Please resend your message with full chat history included"
                                    }
                                },
                                user_id,
                                device_fingerprint_hash
                            )
                            return  # Stop processing until client provides history
                        else:
                            # New chat - no history exists, proceed with empty history
                            logger.info(f"New chat {chat_id} has no cached history (expected). Proceeding with empty history.")

                    # Log final validation result
                    if is_existing_chat:
                        logger.info(f"History validation passed for existing chat {chat_id}: using {actual_previous_messages} cached messages (expected {expected_previous_messages})")
                    else:
                        logger.info(f"New chat {chat_id} proceeding with {actual_previous_messages} cached messages")
                else:
                    # Cache is completely empty - request full history from client
                    # BUT: Only request history for existing chats (messages_v > 1), not new chats
                    if is_existing_chat:
                        # Existing chat with empty cache - request history
                        logger.info(f"AI cache is empty for existing chat {chat_id} (messages_v > 1). Requesting full chat history from client.")
                        await manager.send_personal_message(
                            {
                                "type": "request_chat_history",
                                "payload": {
                                    "chat_id": chat_id,
                                    "reason": "cache_miss",
                                    "message": "Please resend your message with full chat history included"
                                }
                            },
                            user_id,
                            device_fingerprint_hash
                        )
                        return  # Stop processing until client provides history
                    else:
                        # New chat - no history exists, proceed with empty history
                        logger.info(f"New chat {chat_id} has no cached history (expected). Proceeding with empty history.")
            
            # Ensure the current message (which triggered the AI) is the last one in the history.
            current_message_in_history = any(
                m.content == content_plain and 
                m.created_at == client_timestamp_unix and 
                m.role == role # Check role instead of sender_name for "user"
                for m in message_history_for_ai
            )

            if not current_message_in_history:
                logger.debug(f"Current user message {message_id} not found in history. Appending it now.")
                
                # CRITICAL FIX: Resolve embed references in the current message content
                # The content_plain may contain embed references like {"type": "code", "embed_id": "..."}
                # These need to be replaced with actual embed content for the AI to understand
                resolved_current_content = content_plain
                try:
                    from backend.core.api.app.services.embed_service import EmbedService
                    embed_service = EmbedService(
                        cache_service=cache_service,
                        directus_service=directus_service,
                        encryption_service=encryption_service
                    )
                    resolved_current_content = await embed_service.resolve_embed_references_in_content(
                        content=content_plain,
                        chat_id=chat_id,
                        user_id=user_id,
                        encryption_service=encryption_service,
                        user_vault_key_id=user_vault_key_id
                    )
                    if resolved_current_content != content_plain:
                        logger.info(f"Resolved embed references in current user message {message_id}. "
                                   f"Original length: {len(content_plain)}, Resolved length: {len(resolved_current_content)}")
                except Exception as e_resolve:
                    logger.warning(f"Failed to resolve embed references in current message {message_id}: {e_resolve}. Using original content.")
                    resolved_current_content = content_plain
                
                message_history_for_ai.append(
                    AIHistoryMessage(
                        role=role, # Current message's role
                        sender_name=final_sender_name, # Current message's sender_name
                        content=resolved_current_content, # Resolved content with embeds replaced
                        created_at=client_timestamp_unix
                    )
                )
            # Ensure the current message is the last one if it was added or already present
            message_history_for_ai = sorted(message_history_for_ai, key=lambda m: m.created_at)


            logger.debug(f"Final AI message history for chat {chat_id} has {len(message_history_for_ai)} messages.")
            
            history_time = time.time() - history_start
            logger.info(f"[PERF] Message history construction took {history_time:.3f}s, final history has {len(message_history_for_ai)} messages")

        except Exception as e_hist:
            logger.error(f"Failed to construct message history for AI for chat {chat_id}: {e_hist}", exc_info=True)
            # Proceed with at least the current message if history construction failed
            message_history_for_ai = [
                AIHistoryMessage(sender_name="user", content=content_plain, created_at=client_timestamp_unix)
            ]


        # 2. Fetch active_focus_id from chat metadata
        # Note: For AI processing, we need plaintext data (fast inference)
        # The client should send decrypted data when needed for AI processing
        active_focus_id_for_ai: Optional[str] = None
        # mate_id_for_ask_request: Optional[str] = None # Mate ID is determined by preprocessor

        # Get decrypted focus_id from client for AI processing
        active_focus_id_for_ai = message_payload_from_client.get("active_focus_id")
        
        if not active_focus_id_for_ai:
            logger.debug(f"No active_focus_id provided by client for chat {chat_id}. AI will use default focus.")
        
        # chat_has_title_from_client was already extracted earlier (line 71)
        # This flag is critical for determining if metadata (title, category, icon) should be generated
        logger.debug(f"Chat {chat_id} has_title flag from client: {chat_has_title_from_client}")
        
        # Parse app settings/memories metadata from client
        # Format: ["code-preferred_technologies", "travel-trips", ...]
        # Client is the source of truth since only the client can decrypt this data
        app_settings_memories_metadata_from_client = payload.get("app_settings_memories_metadata")
        if app_settings_memories_metadata_from_client:
            if isinstance(app_settings_memories_metadata_from_client, list):
                logger.info(f"Received {len(app_settings_memories_metadata_from_client)} app settings/memories metadata keys from client: {app_settings_memories_metadata_from_client}")
            else:
                logger.warning(f"app_settings_memories_metadata is not a list: {type(app_settings_memories_metadata_from_client)}, ignoring")
                app_settings_memories_metadata_from_client = None
        
        # 3. Construct AskSkillRequest payload
        # mate_id is set to None here; the AI app's preprocessor will select the appropriate mate.
        # If the user could explicitly select a mate for a chat, that pre-selected mate_id would be passed here.
        
        # Get user's timezone and system language for AI context
        # Fetch user data once from cache to avoid multiple cache lookups
        user_data_for_prefs = await cache_service.get_user_by_id(user_id)
        user_preferences_dict = {}
        if user_data_for_prefs and isinstance(user_data_for_prefs, dict):
            user_timezone = user_data_for_prefs.get("timezone")
            if user_timezone:
                user_preferences_dict["timezone"] = user_timezone
                logger.debug(f"Including user timezone '{user_timezone}' in AI request for user {user_id}")
            # Include user's system/UI language (ISO 639-1 code, e.g., "en", "de")
            # Used by postprocessor to generate new chat suggestions in the user's interface language
            user_system_language = user_data_for_prefs.get("language", "en")
            user_preferences_dict["language"] = user_system_language
            logger.debug(f"Including user system language '{user_system_language}' in AI request for user {user_id}")
        
        mentioned_settings_memories_cleartext = message_payload_from_client.get("mentioned_settings_memories_cleartext")
        if mentioned_settings_memories_cleartext is not None and not isinstance(mentioned_settings_memories_cleartext, dict):
            mentioned_settings_memories_cleartext = None
            logger.warning("mentioned_settings_memories_cleartext is not a dict, ignoring")

        ai_request_payload = AskSkillRequestSchema(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id, # Pass the actual user_id
            user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(), # Pass the hashed user_id
            message_history=message_history_for_ai,
            chat_has_title=chat_has_title_from_client, # Pass the flag to preprocessing
            is_incognito=is_incognito, # Pass the incognito flag
            mate_id=None, # Let preprocessor determine the mate unless a specific one is tied to the chat
            active_focus_id=active_focus_id_for_ai,
            user_preferences=user_preferences_dict,
            app_settings_memories_metadata=app_settings_memories_metadata_from_client,  # Client-provided metadata (source of truth)
            mentioned_settings_memories_cleartext=mentioned_settings_memories_cleartext,  # Cleartext for @memory mentions so backend does not re-request
        )
        logger.debug(f"Constructed AskSkillRequest with {len(message_history_for_ai)} messages in history")

        # 4. Check if there's an active AI task for this chat
        # If so, queue the message instead of starting a new task
        active_task_id = await cache_service.get_active_ai_task(chat_id)
        
        if active_task_id:
            # There's an active task - queue this message instead
            logger.info(f"Active AI task {active_task_id} exists for chat {chat_id}. Queueing message {message_id}.")
            
            # Queue the message data for later processing
            queued_success = await cache_service.queue_message(
                chat_id=chat_id,
                message_data=ai_request_payload.model_dump()
            )
            
            if queued_success:
                # Notify client that message is queued
                await manager.send_personal_message(
                    message={
                        "type": "message_queued",
                        "payload": {
                            "chat_id": chat_id,
                            "user_message_id": message_id,
                            "active_task_id": active_task_id,
                            "message": "Press enter again to stop previous response"
                        }
                    },
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
                logger.info(f"Message {message_id} queued for chat {chat_id} with active task {active_task_id}")
            else:
                logger.error(f"Failed to queue message {message_id} for chat {chat_id}")
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Failed to queue message. Please try again."}},
                    user_id, device_fingerprint_hash
                )
            return  # Exit early - message is queued, don't start new task
        
        # No active task - proceed with normal processing
        # 5. Call AI app's FastAPI endpoint to execute the ask skill
        # The AI app will handle the request and dispatch to its own Celery worker
        ai_task_id = None   # Initialize to None

        ai_call_start = time.time()
        try:
            # Call the AI app's FastAPI endpoint for the ask skill
            # BaseApp registers routes as /skills/{skill_id}, so for ask skill it's /skills/ask
            ai_app_url = "http://app-ai:8000/skills/ask"
            
            # Prepare the request payload - AskSkill expects AskSkillRequest
            request_payload = ai_request_payload.model_dump()
            
            logger.debug(f"Calling AI app ask skill endpoint: {ai_app_url} for chat {chat_id}, message {message_id}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    ai_app_url,
                    json=request_payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                response_data = response.json()
                
                # AskSkillResponse contains task_id
                ai_task_id = response_data.get("task_id")
                ai_call_time = time.time() - ai_call_start
                logger.info(f"[PERF] AI app call took {ai_call_time:.3f}s, Task ID: {ai_task_id} for chat {chat_id}, message {message_id}")
                logger.info(f"AI app ask skill executed successfully. Task ID: {ai_task_id} for chat {chat_id}, message {message_id}")

            # Mark this chat as having an active AI task
            if ai_task_id:
                await cache_service.set_active_ai_task(chat_id, ai_task_id)

                # Send acknowledgement with task_id to the originating client
                await manager.send_personal_message(
                    message={
                        "type": "ai_task_initiated",
                        "payload": {
                            "chat_id": chat_id,
                            "user_message_id": message_id,
                            "ai_task_id": ai_task_id,
                            "status": "processing_started"
                        }
                    },
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
                logger.debug(f"Sent 'ai_task_initiated' ack to client for task {ai_task_id}")
            else:
                logger.warning(f"AI app returned response but no task_id found. Response: {response_data}")

        except httpx.HTTPStatusError as e_ai_task:
            logger.error(f"HTTP error calling AI app ask skill endpoint for chat {chat_id}: {e_ai_task.response.status_code} - {e_ai_task.response.text}", exc_info=True)
            # Attempt to send an error message to the client
            try:
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Could not initiate AI response. Please try again."}},
                    user_id, device_fingerprint_hash
                )
            except Exception as e_send_err:
                logger.error(f"Failed to send error to client after AI task dispatch failure: {e_send_err}")
        except httpx.RequestError as e_ai_task:
            logger.error(f"Request error calling AI app ask skill endpoint for chat {chat_id}: {e_ai_task}", exc_info=True)
            # Attempt to send an error message to the client
            try:
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Could not connect to AI service. Please try again."}},
                    user_id, device_fingerprint_hash
                )
            except Exception as e_send_err:
                logger.error(f"Failed to send error to client after AI task dispatch failure: {e_send_err}")
        except Exception as e_ai_task:
            logger.error(f"Failed to call AI app ask skill endpoint for chat {chat_id}: {e_ai_task}", exc_info=True)
            # Attempt to send an error message to the client
            try:
                await manager.send_personal_message(
                    {"type": "error", "payload": {"message": "Could not initiate AI response. Please try again."}},
                    user_id, device_fingerprint_hash
                )
            except Exception as e_send_err:
                logger.error(f"Failed to send error to client after AI task dispatch failure: {e_send_err}")
        # --- END AI SKILL INVOCATION ---
        
        handler_total_time = time.time() - handler_start_time
        logger.info(f"[PERF] Message handler completed in {handler_total_time:.3f}s for chat_id={chat_id}, message_id={message_id}")

    except Exception as e: # This is the outer try-except for the whole handler
        handler_total_time = time.time() - handler_start_time
        logger.error(f"[PERF] Message handler failed after {handler_total_time:.3f}s for chat_id={payload.get('chat_id') if payload else 'unknown'}: {e}", exc_info=True)
        logger.error(f"Error in handle_message_received (new message) from {user_id}/{device_fingerprint_hash}: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Error processing your message on the server."}},
                user_id,
                device_fingerprint_hash
            )
        except Exception as e_send:
            logger.error(f"Failed to send error to {user_id}/{device_fingerprint_hash} after main error: {e_send}")
