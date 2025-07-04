import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect, status
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
# Import the main fingerprint generator and the model
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash

logger = logging.getLogger(__name__)

async def get_current_user_ws(
    websocket: WebSocket
) -> dict:
    """
    Verify WebSocket connection using auth token from cookie and device fingerprint.
    Closes connection and raises WebSocketDisconnect on failure.
    Returns user_id and device_fingerprint_hash on success.
    """
    logger.info("Attempting WebSocket authentication") # Log entry point and headers
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

        # 2. Verify device fingerprint with retry mechanism for potential race conditions
        max_retries = 5
        retry_delay_seconds = 0.3  # 300ms
        device_hash_recognized = False

        try:
            # Generate the device hash (OS:Country:UserID)
            device_hash, _, _, _, _, _, _ = generate_device_fingerprint_hash(websocket, user_id)
            logger.info(f"Calculated WebSocket fingerprint for user {user_id}: Hash={device_hash[:8]}...")
        except Exception as e:
            logger.error(f"Error calculating WebSocket fingerprint for user {user_id}: {e}", exc_info=True)
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")
            raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")

        for attempt in range(max_retries):
            known_device_hashes = await directus_service.get_user_device_hashes(user_id)
            if device_hash in known_device_hashes:
                logger.info(f"Device hash {device_hash[:8]}... recognized for user {user_id} on attempt {attempt + 1}.")
                device_hash_recognized = True
                break  # Exit loop on success
            
            logger.info(f"Device hash {device_hash[:8]}... not yet found for user {user_id} on attempt {attempt + 1}/{max_retries}. Retrying in {retry_delay_seconds}s...")
            await asyncio.sleep(retry_delay_seconds)

        if not device_hash_recognized:
            logger.warning(f"WebSocket connection denied after {max_retries} retries: Unknown device hash {device_hash[:8]}... for user {user_id}.")
            reason = "Device mismatch"
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
            raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason=reason)

        # 3. Authentication successful, device known
        logger.info(f"WebSocket authenticated: User {user_id}, Device {device_hash}")
        return {"user_id": user_id, "device_fingerprint_hash": device_hash, "user_data": user_data}

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
