import logging
import time
import json

logger = logging.getLogger(__name__)

from app.schemas.chat import ChatResponse, MessageResponse
from datetime import datetime

async def handle_initial_sync(
    cache_service,
    directus_service,
    encryption_service,
    manager,
    user_id,
    device_fingerprint_hash,
    websocket
):
    final_chat_entries_dict = {}
    processed_metadata_list = []
    chat_response_list = []

    try:
        # 1. Try fetching chat list metadata from cache
        cached_metadata = await cache_service.get_chat_list_metadata(user_id)

        if cached_metadata:
            logger.debug(f"Cache HIT for chat list metadata for user {user_id}. Found {len(cached_metadata)} entries.")
            processed_metadata_list = cached_metadata
        else:
            logger.debug(f"Cache MISS for chat list metadata for user {user_id}. Fetching from Directus.")
            directus_chats_metadata = await directus_service.get_user_chats_metadata(user_id)
            logger.debug(f"Fetched {len(directus_chats_metadata)} chats from Directus for user {user_id}")

            # Decrypt titles and prepare list for caching
            decrypted_metadata_for_cache = []
            for chat_meta in directus_chats_metadata:
                chat_id = chat_meta.get("id")
                encrypted_title = chat_meta.get("encrypted_title")
                vault_key_id = chat_meta.get("vault_key_id")
                last_updated = chat_meta.get("updated_at")

                decrypted_title = "Untitled Chat"
                if encrypted_title and vault_key_id:
                    try:
                        decrypted_title = await encryption_service.decrypt_with_chat_key(encrypted_title, vault_key_id)
                        if not decrypted_title:
                            decrypted_title = "Decryption Error"
                    except Exception as decrypt_err:
                        logger.error(f"Failed to decrypt title for chat {chat_id}: {decrypt_err}")
                        decrypted_title = "Decryption Error"
                elif not encrypted_title:
                    logger.warning(f"Chat {chat_id} has no encrypted_title.")

                processed_entry = {
                    "id": chat_id,
                    "title": decrypted_title,
                    "lastUpdated": last_updated,
                    "_version": chat_meta.get("_version")
                }
                decrypted_metadata_for_cache.append(processed_entry)

            # Store the processed list in cache
            if decrypted_metadata_for_cache:
                await cache_service.set_chat_list_metadata(user_id, decrypted_metadata_for_cache)
                logger.debug(f"Stored fetched & decrypted chat list metadata in cache for user {user_id}")

            processed_metadata_list = decrypted_metadata_for_cache

        # 3. Fetch all active drafts from Redis
        draft_keys_pattern = f"draft:{user_id}:*:*"
        active_draft_keys = await cache_service.get_keys_by_pattern(draft_keys_pattern)
        user_drafts = {}
        logger.debug(f"Found {len(active_draft_keys)} potential draft keys for user {user_id}")
        for key in active_draft_keys:
            draft_data = await cache_service.get(key)
            if draft_data and isinstance(draft_data, dict):
                parts = key.split(':')
                if len(parts) >= 4:
                    draft_chat_id = parts[2]
                    draft_data['lastUpdated'] = draft_data.get('lastUpdated', time.time())
                    user_drafts[draft_chat_id] = draft_data
                    logger.debug(f"Fetched draft data for chat_id: {draft_chat_id}")
                else:
                    logger.warning(f"Skipping draft key with unexpected format: {key}")
            else:
                logger.warning(f"Could not fetch or parse draft data for key: {key}")

        # 4. Merge & Format
        for chat_entry in processed_metadata_list:
            chat_id = chat_entry.get("id")
            if not chat_id:
                continue

            chat_meta_key = f"chat:{chat_id}:metadata"
            chat_metadata = await cache_service.get(chat_meta_key)
            decrypted_title = "Untitled Chat"
            decrypted_draft = None
            version = 1
            created_at = None
            updated_at = None
            last_message_timestamp = None
            messages = []

            if chat_metadata and isinstance(chat_metadata, dict):
                encrypted_title = chat_metadata.get("encrypted_title")
                encrypted_draft = chat_metadata.get("encrypted_draft")
                vault_key_reference = chat_metadata.get("vault_key_reference")
                version = chat_metadata.get("version", 1)
                created_at = chat_metadata.get("created_at")
                updated_at = chat_metadata.get("updated_at")
                last_message_timestamp = chat_metadata.get("last_message_timestamp")
                if encrypted_title and vault_key_reference:
                    try:
                        decrypted_title = await encryption_service.decrypt_with_chat_key(encrypted_title, vault_key_reference)
                        if not decrypted_title:
                            decrypted_title = "Decryption Error"
                    except Exception as decrypt_err:
                        logger.error(f"Failed to decrypt title for chat {chat_id}: {decrypt_err}")
                        decrypted_title = "Decryption Error"
                if encrypted_draft and vault_key_reference:
                    try:
                        decrypted_draft_str = await encryption_service.decrypt_with_chat_key(encrypted_draft, vault_key_reference)
                        decrypted_draft = json.loads(decrypted_draft_str) if decrypted_draft_str else None
                    except Exception as decrypt_err:
                        logger.error(f"Failed to decrypt draft for chat {chat_id}: {decrypt_err}")
                        decrypted_draft = None
            else:
                decrypted_title = chat_entry.get("title", "Untitled Chat")

            is_draft = chat_id in user_drafts

            # Convert timestamps to datetime if needed
            def to_dt(val):
                if isinstance(val, datetime):
                    return val
                try:
                    return datetime.fromtimestamp(val)
                except Exception:
                    return None

            chat_response = ChatResponse(
                id=chat_id,
                title=decrypted_title,
                draft=decrypted_draft,
                version=version,
                created_at=to_dt(created_at),
                updated_at=to_dt(updated_at),
                last_message_timestamp=to_dt(last_message_timestamp),
                messages=messages
            )
            chat_response_list.append({
                **chat_response.dict(),
                "isPersisted": True,
                "isDraft": is_draft
            })

        for draft_chat_id, draft_data in user_drafts.items():
            if draft_chat_id not in [c["id"] for c in chat_response_list]:
                draft_content = draft_data.get('content')
                draft_last_updated = draft_data.get('lastUpdated')

                chat_meta_key = f"chat:{draft_chat_id}:metadata"
                chat_metadata = await cache_service.get(chat_meta_key)
                decrypted_title = None
                decrypted_draft = None
                version = 1
                created_at = None
                updated_at = None
                last_message_timestamp = None
                messages = []

                if chat_metadata and isinstance(chat_metadata, dict):
                    encrypted_title = chat_metadata.get("encrypted_title")
                    encrypted_draft = chat_metadata.get("encrypted_draft")
                    vault_key_reference = chat_metadata.get("vault_key_reference")
                    version = chat_metadata.get("version", 1)
                    created_at = chat_metadata.get("created_at")
                    updated_at = chat_metadata.get("updated_at")
                    last_message_timestamp = chat_metadata.get("last_message_timestamp")
                    if encrypted_title and vault_key_reference:
                        try:
                            decrypted_title = await encryption_service.decrypt_with_chat_key(encrypted_title, vault_key_reference)
                        except Exception as decrypt_err:
                            logger.error(f"Failed to decrypt title for draft chat {draft_chat_id}: {decrypt_err}")
                    if encrypted_draft and vault_key_reference:
                        try:
                            decrypted_draft_str = await encryption_service.decrypt_with_chat_key(encrypted_draft, vault_key_reference)
                            decrypted_draft = json.loads(decrypted_draft_str) if decrypted_draft_str else None
                        except Exception as decrypt_err:
                            logger.error(f"Failed to decrypt draft content for chat {draft_chat_id}: {decrypt_err}")

                if decrypted_title is None:
                    decrypted_title = "New Chat"
                if decrypted_draft is None:
                    decrypted_draft = draft_content

                def to_dt(val):
                    if isinstance(val, datetime):
                        return val
                    try:
                        return datetime.fromtimestamp(val)
                    except Exception:
                        return None

                chat_response = ChatResponse(
                    id=draft_chat_id,
                    title=decrypted_title,
                    draft=decrypted_draft,
                    version=version,
                    created_at=to_dt(created_at),
                    updated_at=to_dt(updated_at),
                    last_message_timestamp=to_dt(last_message_timestamp),
                    messages=messages
                )
                chat_response_list.append({
                    **chat_response.dict(),
                    "isPersisted": False,
                    "isDraft": True
                })
                logger.debug(f"Added 'new chat' draft entry for chat_id: {draft_chat_id}")

        chat_list_for_payload = sorted(
            chat_response_list,
            key=lambda x: x.get('updated_at', 0) or 0,
            reverse=True
        )

        logger.info(f"Sending initial_sync_data with {len(chat_list_for_payload)} entries to {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            {"type": "initial_sync_data", "payload": {"chats": chat_list_for_payload, "lastOpenChatId": None}},
            user_id,
            device_fingerprint_hash
        )

    except Exception as sync_err:
        logger.error(f"Error preparing initial_sync_data for {user_id}/{device_fingerprint_hash}: {sync_err}", exc_info=True)
        await manager.send_personal_message(
            {"type": "initial_sync_data", "payload": {"chats": [], "lastOpenChatId": None, "error": "Failed to load chat list"}},
            user_id,
            device_fingerprint_hash
        )