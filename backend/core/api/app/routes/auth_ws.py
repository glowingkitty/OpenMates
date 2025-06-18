import logging
from fastapi import WebSocket, WebSocketDisconnect, status
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
# Import the main fingerprint generator and the model
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint, DeviceFingerprint, _extract_client_ip # Keep _extract_client_ip if needed elsewhere, or remove if not
from backend.core.api.app.utils.device_cache import check_device_in_cache, store_device_in_cache

logger = logging.getLogger(__name__)

async def get_current_user_ws(
    websocket: WebSocket
) -> dict:
    """
    Verify WebSocket connection using auth token from cookie and device fingerprint.
    Closes connection and raises WebSocketDisconnect on failure.
    Returns user_id and device_fingerprint_hash on success.
    """
    logger.info(f"Attempting WebSocket authentication") # Log entry point and headers
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
        token_suffix = auth_refresh_token[-6:] if auth_refresh_token else "N/A"
        logger.info(f"Checking cache for user with token ending ...{token_suffix}")
        user_data = await cache_service.get_user_by_token(auth_refresh_token)
        logger.info(f"Cache check result for token ...{token_suffix}: {'Found' if user_data else 'Not Found'}")
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
            current_fingerprint: DeviceFingerprint = generate_device_fingerprint(websocket)
            # Generate both the full hash (with session) and the base hash (without session)
            device_fingerprint_hash = current_fingerprint.calculate_stable_hash(include_session_id=True)
            base_fingerprint_hash = current_fingerprint.calculate_stable_hash(include_session_id=False)
            
            logger.info(f"Calculated WebSocket fingerprint for user {user_id}: Full Hash={device_fingerprint_hash}, Base Hash={base_fingerprint_hash}")
        except Exception as e:
            logger.error(f"Error calculating WebSocket fingerprint for user {user_id}: {e}", exc_info=True)
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")
            raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")

        # Check if the full fingerprint (including session) is already known
        device_exists_in_cache, _ = await check_device_in_cache(
            cache_service, user_id, device_fingerprint_hash
        )

        if not device_exists_in_cache:
            logger.info(f"Full fingerprint {device_fingerprint_hash} not in cache. Verifying base fingerprint {base_fingerprint_hash}.")
            
            # Check if a device with the same BASE fingerprint is known
            stored_base_device_data = await directus_service.get_stored_device_data(user_id, base_fingerprint_hash)

            if stored_base_device_data is None:
                logger.warning(f"WebSocket connection denied: Unknown base device for user {user_id}. Base Fingerprint: {base_fingerprint_hash}")
                reason = "Device mismatch"
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
                raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
            else:
                # Base device is known, so this is a new session on a trusted device.
                # Store the new FULL fingerprint to allow this specific session.
                logger.info(f"Base device recognized for user {user_id}. Storing new session fingerprint: {device_fingerprint_hash}")
                device_location_str = f"{current_fingerprint.city}, {current_fingerprint.country_code}" if current_fingerprint.city and current_fingerprint.country_code else current_fingerprint.country_code or "Unknown"
                
                # Add the new full fingerprint to Directus
                await directus_service.update_user_device_record(
                    user_id=user_id,
                    current_fingerprint=current_fingerprint
                )
                # Add the new full fingerprint to the cache
                await store_device_in_cache(
                    cache_service=cache_service,
                    user_id=user_id,
                    device_fingerprint=device_fingerprint_hash,
                    device_location=device_location_str,
                    is_new_device=False
                )

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
