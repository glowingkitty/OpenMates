"""Persist sparse email preference changes against fresh durable account state."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.notification_email_preferences import (
    _json_object,
    load_notification_user,
    resolve_notification_email,
)
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


def _request_fields(payload: Any) -> dict[str, str]:
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    return {"request_id": request_id} if isinstance(request_id, str) and 0 < len(request_id) <= 128 else {}


class NotificationSettingsLockUnavailable(RuntimeError):
    """A settings write cannot proceed without its per-user Redis lease."""


async def _acquire_notification_settings_lock(cache_service: CacheService, user_id: str) -> Any:
    try:
        client = await cache_service.client
        if client is None:
            raise NotificationSettingsLockUnavailable("Notification settings lock store unavailable")
        lock = client.lock(f"email:notification:settings:{user_id}", timeout=120)
        acquired = await lock.acquire(blocking=True, blocking_timeout=10)
    except Exception as exc:
        raise NotificationSettingsLockUnavailable("Could not acquire notification settings lock") from exc
    if not acquired:
        raise NotificationSettingsLockUnavailable("Notification settings lock busy")
    return lock


async def _require_notification_settings_lock(lock: Any) -> None:
    """Extend the owned lease immediately before the durable account PATCH."""
    try:
        if await lock.extend(120, replace_ttl=True):
            return
    except Exception as exc:
        raise NotificationSettingsLockUnavailable("Notification settings lock state unavailable") from exc
    raise NotificationSettingsLockUnavailable("Notification settings lock expired")


async def handle_email_notification_settings_get(
    manager: ConnectionManager,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    """Send a fresh durable settings snapshot without recording a user choice."""
    request_fields = _request_fields(payload)
    try:
        user = await load_notification_user(directus_service, user_id)
        if not user:
            raise ValueError("notification user unavailable")
        await manager.send_personal_message(
            message={
                "type": "email_notification_settings_snapshot",
                "payload": {
                    "enabled": user.get("email_notifications_enabled") is True,
                    "preferences": _json_object(user.get("email_notification_preferences")),
                    "choices": _json_object(user.get("email_notification_preference_choices")),
                    "backup_reminder_interval_days": user.get("backup_reminder_interval_days") or 30,
                    **request_fields,
                },
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
    except Exception:
        logger.exception("Failed to load email notification settings for user %s", user_id[:8])
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Could not load notification settings. Please try again.", **request_fields}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )


async def handle_email_notification_settings(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    """Merge preference patches, record user choices, then acknowledge durable writes."""
    del websocket
    request_fields = _request_fields(payload)
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span
        _otel_span, _otel_token = start_ws_handler_span(
            "email_notification_settings", user_id, payload, user_otel_attrs
        )
    except Exception:
        pass

    async def reject(message: str) -> None:
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": message, **request_fields}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )

    lock = None
    try:
        if not isinstance(payload, dict):
            await reject("Invalid notification settings.")
            return
        if "enabled" in payload and not isinstance(payload["enabled"], bool):
            await reject("Invalid notification setting.")
            return
        patch = payload.get("preferences", {})
        if not isinstance(patch, dict) or any(
            not isinstance(key, str) or not isinstance(value, bool) for key, value in patch.items()
        ):
            await reject("Invalid notification preferences.")
            return

        lock = await _acquire_notification_settings_lock(cache_service, user_id)
        user = await load_notification_user(directus_service, user_id)
        if not user:
            await reject("Could not load notification settings. Please try again.")
            return
        preferences = {**_json_object(user.get("email_notification_preferences")), **patch}
        choices = dict(_json_object(user.get("email_notification_preference_choices")))
        changed_at = datetime.now(timezone.utc).isoformat()
        for key, value in patch.items():
            choices[key] = {"value": value, "source": "user", "updated_at": changed_at}

        enabled = payload.get("enabled", user.get("email_notifications_enabled") is True)
        if "enabled" in payload:
            choices["enabled"] = {"value": enabled, "source": "user", "updated_at": changed_at}
        update_data: dict[str, Any] = {
            "email_notifications_enabled": enabled,
            "email_notification_preferences": preferences,
            "email_notification_preference_choices": choices,
        }

        supplied_email = payload.get("email")
        if supplied_email is not None and not isinstance(supplied_email, str):
            await reject("Invalid notification email.")
            return
        if enabled:
            verified_email = await resolve_notification_email(directus_service, encryption_service, user)
            if not verified_email:
                if payload.get("enabled") is True or supplied_email:
                    await reject("A verified account email is required for notifications.")
                    return
                # A category opt-out must remain writable even on a legacy
                # account whose verified contact was never provisioned.
                update_data["encrypted_notification_email"] = None
            else:
                if supplied_email and supplied_email.strip().casefold() != verified_email.casefold():
                    await reject("Notification email must match your verified account email.")
                    return
                if not user.get("vault_key_id"):
                    await reject("Cannot enable email notifications: encryption key not found.")
                    return
                encrypted, _version = await encryption_service.encrypt_with_user_key(
                    plaintext=verified_email, key_id=user["vault_key_id"]
                )
                if not encrypted:
                    await reject("Failed to encrypt notification email. Please try again.")
                    return
                update_data["encrypted_notification_email"] = encrypted
        else:
            update_data["encrypted_notification_email"] = None

        backup_interval = payload.get("backup_reminder_interval_days")
        if backup_interval is not None:
            try:
                parsed_interval = int(backup_interval)
                if parsed_interval <= 0:
                    raise ValueError("non-positive")
            except (TypeError, ValueError):
                await reject("Invalid backup reminder interval.")
                return
            update_data["backup_reminder_interval_days"] = parsed_interval

        # Durable storage is the acknowledgment boundary; stale cache cannot
        # override an opt-out after this write succeeds.
        await _require_notification_settings_lock(lock)
        if not await directus_service.update_user(user_id, update_data):
            await reject("Failed to save notification settings. Please try again.")
            return
        try:
            if not await cache_service.update_user(user_id, update_data):
                await cache_service.delete_user_cache(user_id)
        except Exception:
            logger.warning("Notification settings cache refresh failed for user %s", user_id[:8])
            try:
                await cache_service.delete_user_cache(user_id)
            except Exception:
                logger.warning("Notification settings cache eviction failed for user %s", user_id[:8])

        result: dict[str, Any] = {"enabled": enabled, "preferences": preferences, "choices": choices}
        if backup_interval is not None:
            result["backup_reminder_interval_days"] = parsed_interval
        await manager.send_personal_message(
            message={"type": "email_notification_settings_ack", "payload": {"success": True, **result, **request_fields}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        await manager.broadcast_to_user(
            message={"type": "email_notification_settings_updated", "payload": result},
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,
        )
    except NotificationSettingsLockUnavailable:
        logger.warning("Notification settings lock unavailable for user %s", user_id[:8])
        await reject("Notification settings are busy. Please try again.")
    except Exception:
        logger.exception("Failed to update email notification settings for user %s", user_id[:8])
        await reject("Failed to save notification settings. Please try again.")
    finally:
        if lock is not None:
            try:
                await lock.release()
            except Exception:
                # Redis rejects release from a stale owner token.
                pass
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span
                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass
