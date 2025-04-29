import logging
from fastapi import WebSocket, WebSocketDisconnect, status
from app.services.cache import CacheService
from app.services.directus import DirectusService
from app.utils.device_fingerprint import get_websocket_device_fingerprint, get_websocket_client_ip, get_location_from_ip
from app.utils.device_cache import check_device_in_cache, store_device_in_cache

logger = logging.getLogger(__name__)

async def get_current_user_ws(
    websocket: WebSocket
) -> dict:
    """
    Verify WebSocket connection using auth token from cookie and device fingerprint.
    Closes connection and raises WebSocketDisconnect on failure.
    Returns user_id and device_fingerprint_hash on success.
    """
    # Access services directly from websocket state
    cache_service: CacheService = websocket.app.state.cache_service
    directus_service: DirectusService = websocket.app.state.directus_service

    # Access cookies directly from the websocket object
    auth_refresh_token = websocket.cookies.get("auth_refresh_token")

    if not auth_refresh_token:
        logger.warning("WebSocket connection denied: Missing or inaccessible 'auth_refresh_token' cookie.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")

    try:
        # 1. Get user data from cache using the extracted token
        user_data = await cache_service.get_user_by_token(auth_refresh_token)
        if not user_data:
            logger.warning(f"WebSocket connection denied: Invalid or expired token (not found in cache for token ending ...{auth_refresh_token[-6:]}).")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")
            raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")

        user_id = user_data.get("user_id")
        if not user_id:
            logger.error("WebSocket connection denied: User data in cache is invalid (missing user_id).")
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")
            raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")

        # 2. Verify device fingerprint using the dedicated utility functions
        try:
            # Use the specific functions for WebSockets
            device_fingerprint_hash = get_websocket_device_fingerprint(websocket)
            client_ip = get_websocket_client_ip(websocket) # Get IP for logging/cache update
            logger.debug(f"Calculated WebSocket fingerprint for user {user_id}: Hash={device_fingerprint_hash}")
        except Exception as e:
            logger.error(f"Error calculating WebSocket fingerprint for user {user_id}: {e}", exc_info=True)
            # Ensure connection is closed before raising disconnect
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")
            raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")

        # Check if device is known using device_cache utility (checks cache first)
        device_exists_in_cache, _ = await check_device_in_cache(
            cache_service, user_id, device_fingerprint_hash
        )

        if not device_exists_in_cache:
            # Not in cache, check database as fallback
            logger.debug(f"Device {device_fingerprint_hash} not in cache for user {user_id}, checking DB.")
            device_in_db = await directus_service.check_user_device(user_id, device_fingerprint_hash)
            if not device_in_db:
                logger.warning(f"WebSocket connection denied: Device mismatch for user {user_id}. Fingerprint: {device_fingerprint_hash}")
                # Check if 2FA is enabled for the user
                if user_data.get("tfa_enabled", False):
                    reason = "Device mismatch, 2FA required"
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                    raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                else:
                    reason = "Device mismatch"
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                    raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
            else:
                # Device is in DB but not cache - add it to cache using device_cache utility
                logger.info(f"Device {device_fingerprint_hash} found in DB for user {user_id}, adding to cache.")
                # Fetch location info first
                try:
                    location_info = get_location_from_ip(client_ip)
                except Exception as loc_e:
                    logger.error(f"Error getting location for IP {client_ip} during cache update: {loc_e}")
                    # Use a default/error location string for the cache entry
                    location_info = {"location_string": "Location Error"} # Ensure this dict structure is handled by store_device_in_cache or adjust

                # Store using the utility function
                await store_device_in_cache(
                    cache_service=cache_service,
                    user_id=user_id,
                    device_fingerprint=device_fingerprint_hash,
                    # Pass the location string extracted from location_info
                    device_location=location_info.get("location_string", "Unknown"),
                    is_new_device=False # It existed in DB, so not strictly new
                )
                # Note: store_device_in_cache handles setting the correct cache key and TTL

        # 3. Authentication successful, device known
        logger.info(f"WebSocket authenticated: User {user_id}, Device {device_fingerprint_hash}")
        return {"user_id": user_id, "device_fingerprint_hash": device_fingerprint_hash, "user_data": user_data}

    except WebSocketDisconnect as e:
        # Re-raise exceptions related to auth failure that already closed the connection
        raise e
    except Exception as e:
        # Ensure token exists before trying to slice it for logging
        token_suffix = auth_refresh_token[-6:] if auth_refresh_token else "N/A"
        logger.error(f"Unexpected error during WebSocket authentication for token ending ...{token_suffix}: {e}", exc_info=True)
        # Attempt to close gracefully before raising disconnect
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Authentication error")
        except Exception:
            pass # Ignore errors during close after another error
        raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Authentication error")