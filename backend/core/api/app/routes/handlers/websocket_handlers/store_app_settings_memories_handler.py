# backend/core/api/app/routes/handlers/websocket_handlers/store_app_settings_memories_handler.py
"""
Handler for storing app settings/memories entries from client to Directus.

When client creates a new app settings/memories entry in the App Store:
1. Client encrypts entry with master key and stores in IndexedDB
2. Client sends encrypted entry to server via this handler
3. Server stores encrypted entry in Directus (zero-knowledge - server never decrypts)
4. Server broadcasts to other logged-in devices for multi-device sync

This enables permanent storage in Directus while maintaining zero-knowledge architecture.

**Field Naming Convention**:
- id: UUID primary key (client-generated)
- hashed_user_id: SHA256 hash of user_id for privacy
- app_id: App identifier (e.g., 'code', 'travel', 'tv')
- item_key: Entry identifier within a category
- item_type: Category/type ID for filtering (e.g., 'preferred_technologies')
- encrypted_item_json: Client-encrypted JSON data
- encrypted_app_key: Encrypted app-specific key for device sync
- created_at, updated_at: Unix timestamps
- item_version: Version for conflict resolution
- sequence_number: Optional ordering

**Size Limits**:
- MAX_ITEM_KEY_BYTES: Maximum size for the item_key field (plain text key identifier)
- MAX_ENCRYPTED_ENTRY_BYTES: Maximum size of the encrypted_item_json payload.
  Accounts for encryption overhead (base64 + IV + auth tag) on top of frontend char limits.
  Frontend limits: single-line 100 chars, multiline 500 chars, generic value 1000 chars.
  Worst-case JSON with all fields + overhead at ~4x: 1000 * 4 = 4 000 bytes. We allow
  20 000 bytes as the backend upper bound — generous enough to absorb overhead while
  blocking clients that bypass the UI.
"""

import logging
import hashlib
import time
from typing import Dict, Any

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Size limits for incoming entry payloads
# ---------------------------------------------------------------------------
# Frontend enforces character limits (500 short / 2000 multiline / 3000 generic).
# These byte limits act as a backend defence-in-depth against clients that bypass
# the UI.  Encryption adds overhead (~1.4x base64 + IV + auth tag), so we allow
# ~50 KB for the encrypted blob and 2 KB for the plaintext item_key.
MAX_ENCRYPTED_ENTRY_BYTES: int = 20_000   # 20 KB upper bound for encrypted_item_json
MAX_ITEM_KEY_BYTES: int = 500            # 500 bytes upper bound for the plain-text item_key


async def handle_store_app_settings_memories_entry(
    websocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles storing a new or updated app settings/memories entry from client.
    
    **Zero-Knowledge Architecture**: 
    - Server stores encrypted data directly in Directus without decrypting
    - Entry is encrypted client-side with master key before sending
    - Server cannot read entry contents
    
    **Multi-Device Sync**:
    - After storing in Directus, broadcasts to all other logged-in devices
    - Other devices receive the encrypted entry and store in their IndexedDB
    
    Args:
        websocket: WebSocket connection
        manager: ConnectionManager instance
        cache_service: CacheService instance
        directus_service: DirectusService instance
        user_id: User ID
        device_fingerprint_hash: Device fingerprint hash (source device)
        payload: Payload containing the encrypted entry data
    """
    try:
        # Extract entry data from payload
        entry = payload.get("entry")
        
        if not entry:
            logger.warning(f"[StoreAppSettingsMemories] Invalid payload from user {user_id[:8]}...: missing entry")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing entry data"}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Validate required fields
        # Field names must match frontend interface in chatSyncServiceSenders.ts
        entry_id = entry.get("id")
        app_id = entry.get("app_id")
        item_key = entry.get("item_key")
        item_type = entry.get("item_type")  # Category ID for filtering (e.g., 'preferred_technologies')
        encrypted_item_json = entry.get("encrypted_item_json")
        encrypted_app_key = entry.get("encrypted_app_key", "")
        created_at = entry.get("created_at")
        updated_at = entry.get("updated_at")
        item_version = entry.get("item_version", 1)
        sequence_number = entry.get("sequence_number")
        
        if not all([entry_id, app_id, item_key, encrypted_item_json is not None]):
            logger.warning(f"[StoreAppSettingsMemories] Invalid entry from user {user_id[:8]}...: missing required fields (id={entry_id}, app_id={app_id}, item_key={item_key}, encrypted_item_json={'present' if encrypted_item_json else 'missing'})")
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Missing required entry fields"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Validate payload sizes to prevent storage abuse and oversized context injection.
        # These are defence-in-depth limits; the frontend enforces tighter character limits.
        item_key_str = str(item_key)
        if len(item_key_str.encode("utf-8")) > MAX_ITEM_KEY_BYTES:
            logger.warning(
                f"[StoreAppSettingsMemories] item_key too large from user {user_id[:8]}...: "
                f"{len(item_key_str)} chars (max {MAX_ITEM_KEY_BYTES} bytes)"
            )
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Entry key exceeds maximum allowed size"}},
                user_id,
                device_fingerprint_hash
            )
            return

        encrypted_json_str = str(encrypted_item_json)
        if len(encrypted_json_str.encode("utf-8")) > MAX_ENCRYPTED_ENTRY_BYTES:
            logger.warning(
                f"[StoreAppSettingsMemories] encrypted_item_json too large from user {user_id[:8]}...: "
                f"{len(encrypted_json_str)} bytes (max {MAX_ENCRYPTED_ENTRY_BYTES})"
            )
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Entry data exceeds maximum allowed size"}},
                user_id,
                device_fingerprint_hash
            )
            return

        # Hash user ID for Directus storage (zero-knowledge)
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        logger.info(f"[StoreAppSettingsMemories] Processing entry {entry_id} for user {user_id[:8]}..., app {app_id}, type {item_type}, key {item_key}")
        
        # Prepare Directus payload with consistent field names
        current_timestamp = int(time.time())
        
        directus_payload = {
            "id": entry_id,  # Use client-generated ID
            "hashed_user_id": hashed_user_id,
            "app_id": app_id,
            "item_key": item_key,
            "item_type": item_type,  # Category ID for filtering
            "encrypted_item_json": encrypted_item_json,  # Client-encrypted data
            "encrypted_app_key": encrypted_app_key,
            "created_at": created_at or current_timestamp,
            "updated_at": updated_at or current_timestamp,
            "item_version": item_version,
            "sequence_number": sequence_number
        }
        
        try:
            # Check if entry already exists (by ID)
            existing_entries = await directus_service.get_items(
                "user_app_settings_and_memories",
                params={
                    "filter": {"id": {"_eq": entry_id}},
                    "limit": 1
                }
            )
            existing_entry = existing_entries[0] if existing_entries else None
            
            if existing_entry:
                # Update existing entry
                # Only update if incoming version is higher (conflict resolution)
                existing_version = existing_entry.get("item_version", 1)
                if item_version >= existing_version:
                    await directus_service.update_item(
                        "user_app_settings_and_memories",
                        entry_id,
                        directus_payload
                    )
                    logger.info(f"[StoreAppSettingsMemories] Updated entry {entry_id} in Directus (v{existing_version} -> v{item_version})")
                else:
                    logger.info(f"[StoreAppSettingsMemories] Skipped entry {entry_id} - server has newer version (v{existing_version} > v{item_version})")
            else:
                # Create new entry
                await directus_service.create_item(
                    "user_app_settings_and_memories",
                    directus_payload
                )
                logger.info(f"[StoreAppSettingsMemories] Created entry {entry_id} in Directus")
                
        except Exception as directus_error:
            logger.error(f"[StoreAppSettingsMemories] Directus error for entry {entry_id}: {directus_error}", exc_info=True)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": f"Failed to store entry: {str(directus_error)}"}},
                user_id,
                device_fingerprint_hash
            )
            return
        
        # Send success acknowledgment to source device
        await manager.send_personal_message(
            {
                "type": "app_settings_memories_entry_stored",
                "payload": {
                    "entry_id": entry_id,
                    "app_id": app_id,
                    "item_key": item_key,
                    "item_type": item_type,
                    "success": True
                }
            },
            user_id,
            device_fingerprint_hash
        )
        
        # Broadcast to other logged-in devices for multi-device sync
        # This sends the full encrypted entry so other devices can store it in IndexedDB
        sync_message = {
            "type": "app_settings_memories_entry_synced",
            "payload": {
                "entries": [entry],  # Send as array for consistency with sync_ready event
                "entry_count": 1,
                "source_device": device_fingerprint_hash  # So receiving devices know where it came from
            }
        }
        
        await manager.broadcast_to_user(
            message=sync_message,
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash  # Don't send back to source device
        )
        
        logger.info(f"[StoreAppSettingsMemories] Successfully stored and broadcasted entry {entry_id} for user {user_id[:8]}...")
        
    except Exception as e:
        logger.error(f"[StoreAppSettingsMemories] Error handling entry for user {user_id[:8]}...: {e}", exc_info=True)
        try:
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to process app settings/memories entry"}},
                user_id,
                device_fingerprint_hash
            )
        except Exception as send_err:
            logger.error(f"[StoreAppSettingsMemories] Failed to send error message: {send_err}")
