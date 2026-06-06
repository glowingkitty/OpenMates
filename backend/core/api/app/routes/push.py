# backend/core/api/app/routes/push.py
"""
Push notification routes — browser Web Push and native Apple device registration.

Architecture:
- GET  /v1/push/vapid-public-key  → returns the server VAPID public key (no auth required)
- POST /v1/push/subscribe          → saves/updates a browser PushSubscription for the current user
- DELETE /v1/push/subscribe        → removes a browser PushSubscription for the current user

The subscription is stored in Directus user field `push_notification_subscription` as a JSON
string (the raw browser PushSubscription object: {endpoint, keys: {p256dh, auth}}).
The `push_notification_enabled` flag is set to True/False accordingly.

See docs/architecture/notifications.md for the full notification flow.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional
import json

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_directus_service, get_cache_service
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/push", tags=["Push Notifications"])
notifications_router = APIRouter(prefix="/v1/notifications", tags=["Push Notifications"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class PushSubscribeRequest(BaseModel):
    """Browser PushSubscription JSON passed from the frontend after subscribe()."""
    endpoint: str
    keys: dict  # {p256dh: str, auth: str}
    expirationTime: Optional[int] = None  # milliseconds since epoch, or null


class PushVapidKeyResponse(BaseModel):
    vapid_public_key: str


class PushSubscribeResponse(BaseModel):
    success: bool
    message: str


class NativeDeviceRegisterRequest(BaseModel):
    """Native Apple push token registration from the iOS/macOS app."""
    token: str
    platform: str = "apns"
    environment: Optional[str] = None
    notification_public_key: Optional[str] = None
    encryption_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/vapid-public-key", response_model=PushVapidKeyResponse)
async def get_vapid_public_key(request: Request):
    """
    Return the server VAPID public key so the browser can create a PushSubscription.
    No authentication required — the key is public by design.
    """
    push_service = getattr(request.app.state, "push_notification_service", None)
    if push_service is None or not push_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notification service is not available",
        )
    return PushVapidKeyResponse(vapid_public_key=push_service.get_vapid_public_key())


@router.post("/subscribe", response_model=PushSubscribeResponse)
async def subscribe_push(
    request: Request,
    body: PushSubscribeRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Save the browser PushSubscription for the authenticated user.
    Enables push notifications and stores the subscription endpoint + keys.
    """
    user_id = str(current_user.id)
    subscription_json = json.dumps({
        "endpoint": body.endpoint,
        "keys": body.keys,
        "expirationTime": body.expirationTime,
    })

    try:
        updated = await directus_service.update_user(user_id, {
            "push_notification_enabled": True,
            "push_notification_subscription": subscription_json,
        })
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to save subscription")

        # Invalidate cached user so next fetch returns the updated subscription
        await cache_service.delete_user_cache(user_id)
        logger.info(f"[PushRoutes] Saved push subscription for user {user_id[:6]}...")
        return PushSubscribeResponse(success=True, message="Subscription saved")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PushRoutes] Failed to save push subscription for {user_id[:6]}...: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/subscribe", response_model=PushSubscribeResponse)
async def unsubscribe_push(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Remove the browser PushSubscription for the authenticated user.
    Disables push notifications.
    """
    user_id = str(current_user.id)

    try:
        updated = await directus_service.update_user(user_id, {
            "push_notification_enabled": False,
            "push_notification_subscription": None,
        })
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to remove subscription")

        await cache_service.delete_user_cache(user_id)
        logger.info(f"[PushRoutes] Removed push subscription for user {user_id[:6]}...")
        return PushSubscribeResponse(success=True, message="Subscription removed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PushRoutes] Failed to remove push subscription for {user_id[:6]}...: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@notifications_router.post("/register-device", response_model=PushSubscribeResponse)
async def register_native_device(
    body: NativeDeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Save a native Apple APNs device token for the authenticated user.

    The native app already calls this endpoint after APNs registration. Store the
    token in the existing push subscription field with a type discriminator so
    the offline assistant-completion path can dispatch either Web Push or APNs.
    """
    user_id = str(current_user.id)
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing device token")

    platform = body.platform.strip().lower() or "apns"
    if platform not in {"apns", "ios", "macos"}:
        raise HTTPException(status_code=400, detail="Unsupported native push platform")

    subscription_json = json.dumps({
        "type": "apns",
        "token": token,
        "platform": platform,
        "environment": body.environment,
        "notification_public_key": body.notification_public_key,
        "encryption_version": body.encryption_version,
    })

    try:
        updated = await directus_service.update_user(user_id, {
            "push_notification_enabled": True,
            "push_notification_subscription": subscription_json,
        })
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to save device token")

        await cache_service.delete_user_cache(user_id)
        logger.info(f"[PushRoutes] Saved native APNs token for user {user_id[:6]}...")
        return PushSubscribeResponse(success=True, message="Device registered")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PushRoutes] Failed to save native token for {user_id[:6]}...: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
