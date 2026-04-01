"""
WebSocket handler for email notification settings.
Handles enabling/disabling email notifications and updating preferences.

Email is encrypted server-side using the user's vault key before storage.
When enabled, the user's login email is used for notifications.
"""

import logging
from typing import Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


async def handle_email_notification_settings(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict = None,) -> None:
    """
    Handle email notification settings update from client.
    
    Expected payload:
    {
        "enabled": bool,
        "email": str | None,  # Plaintext email when enabling (will be encrypted server-side)
        "preferences": {"aiResponses": bool, "backupReminder": bool},
        "backup_reminder_interval_days": int | None  # Optional; persisted when present
    }
    """
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span, end_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span("email_notification_settings", user_id, payload, user_otel_attrs)
    except Exception:
        pass
    try:
        enabled = payload.get("enabled", False)
        email = payload.get("email")  # Plaintext email from client
        preferences = payload.get("preferences", {"aiResponses": True})
        backup_reminder_interval_days = payload.get("backup_reminder_interval_days")
    
        logger.info(f"Processing email_notification_settings for user {user_id}: enabled={enabled}")
    
        try:
            # Prepare update data
            update_data: dict[str, Any] = {
                "email_notifications_enabled": enabled,
                "email_notification_preferences": preferences
            }

            # Persist backup reminder interval if provided (set from Backup Reminders settings page)
            if backup_reminder_interval_days is not None:
                try:
                    interval_int = int(backup_reminder_interval_days)
                    if interval_int > 0:
                        update_data["backup_reminder_interval_days"] = interval_int
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid backup_reminder_interval_days value for user {user_id}: "
                        f"{backup_reminder_interval_days!r}"
                    )
        
            if enabled and email:
                # Encrypt email using server-side vault encryption
                vault_key_id = await cache_service.get_user_vault_key_id(user_id)
            
                if not vault_key_id:
                    logger.error(f"No vault key ID found for user {user_id}. Cannot encrypt notification email.")
                    await manager.send_personal_message(
                        message={
                            "type": "error",
                            "payload": {"message": "Cannot enable email notifications: encryption key not found. Please log out and log back in."}
                        },
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash
                    )
                    return
            
                # Encrypt email with user's vault key
                encrypted_result = await encryption_service.encrypt_with_user_key(
                    plaintext=email,
                    key_id=vault_key_id
                )
            
                if encrypted_result and encrypted_result[0]:
                    encrypted_email = encrypted_result[0]
                    update_data["encrypted_notification_email"] = encrypted_email
                    logger.debug(f"Successfully encrypted notification email for user {user_id}")
                else:
                    logger.error(f"Failed to encrypt notification email for user {user_id}")
                    await manager.send_personal_message(
                        message={
                            "type": "error",
                            "payload": {"message": "Failed to encrypt email for notifications. Please try again."}
                        },
                        user_id=user_id,
                        device_fingerprint_hash=device_fingerprint_hash
                    )
                    return
            elif not enabled:
                # Clear encrypted email when disabling
                update_data["encrypted_notification_email"] = None
        
            # Update cache first (for fast reads)
            cache_success = await cache_service.update_user(user_id, update_data)
            if cache_success:
                logger.debug(f"Updated email notification settings in cache for user {user_id}")
            else:
                logger.warning(f"Failed to update email notification settings in cache for user {user_id}")
        
            # Update Directus (persistent storage)
            directus_success = await directus_service.update_user(user_id, update_data)
            if directus_success:
                logger.info(f"Successfully saved email notification settings for user {user_id}")
            else:
                logger.error(f"Failed to save email notification settings to Directus for user {user_id}")
                await manager.send_personal_message(
                    message={
                        "type": "error",
                        "payload": {"message": "Failed to save notification settings. Please try again."}
                    },
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
                return
        
            # Build shared payload — include backup interval when it was updated so
            # other devices can keep their local store in sync without a full reload.
            broadcast_payload: dict[str, Any] = {
                "enabled": enabled,
                "preferences": preferences,
            }
            if backup_reminder_interval_days is not None:
                try:
                    interval_int = int(backup_reminder_interval_days)
                    if interval_int > 0:
                        broadcast_payload["backup_reminder_interval_days"] = interval_int
                except (ValueError, TypeError):
                    pass

            # Send success acknowledgement to the requesting device
            await manager.send_personal_message(
                message={
                    "type": "email_notification_settings_ack",
                    "payload": {"success": True, **broadcast_payload}
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
        
            # Broadcast to other devices so they update their local state
            await manager.broadcast_to_user(
                message={
                    "type": "email_notification_settings_updated",
                    "payload": broadcast_payload
                },
                user_id=user_id,
                exclude_device_hash=device_fingerprint_hash
            )
        
            logger.info(f"Email notification settings saved and broadcasted for user {user_id}")
        
        except Exception as e:
            logger.error(f"Error handling email notification settings for user {user_id}: {e}", exc_info=True)
            await manager.send_personal_message(
                message={
                    "type": "error",
                    "payload": {"message": "An error occurred while saving notification settings."}
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )

    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span
                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
