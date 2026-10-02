import asyncio
import hashlib
import logging
from typing import Optional
from fastapi import WebSocket, status
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.cache_user_mixin import canonical_session_user_id
from backend.core.api.app.services.directus import DirectusService
# Import the main fingerprint generator and the model
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.utils.ws_token import verify_ws_token
from backend.core.api.app.services.pair_session_deadline import get_pair_deadline_hash
from backend.core.api.app.services.session_security_state import (
    ensure_legacy_session_hash_state, get_session_state_cached,
)

logger = logging.getLogger(__name__)

async def get_current_user_ws(
    websocket: WebSocket
) -> Optional[dict]:
    """
    Verify WebSocket connection using auth token from cookie and device fingerprint.
    Closes connection and returns None on failure (no exception raised).
    Returns dict with user_id, device_fingerprint_hash, and user_data on success.
    """
    logger.debug("Attempting WebSocket authentication") # Log entry point and headers
    
    # Log request details for Safari/iPad OS debugging
    # Check User-Agent header if available (may not be accessible directly from WebSocket in FastAPI)
    try:
        # Try to get headers if available
        headers = dict(websocket.headers) if hasattr(websocket, 'headers') else {}
        user_agent = headers.get('user-agent', 'unknown')
        if 'safari' in user_agent.lower() and ('ipad' in user_agent.lower() or 'iphone' in user_agent.lower()):
            logger.debug(f"WebSocket auth: Safari iOS/iPad OS detected. User-Agent: {user_agent}")
        
        # Log only parameter presence; credentials and browser identifiers do
        # not belong in request logs, even as prefixes or suffixes.
        query_params = dict(websocket.query_params) if hasattr(websocket, 'query_params') else {}
        if 'token' in query_params:
            logger.debug("WebSocket auth: Token query parameter present")
        if 'sessionId' in query_params:
            logger.debug("WebSocket auth: SessionId query parameter present")
    except Exception as e:
        logger.debug(f"WebSocket auth: Could not extract headers/query params for logging: {e}")
    
    # Access services directly from websocket state
    cache_service: CacheService = websocket.app.state.cache_service
    directus_service: DirectusService = websocket.app.state.directus_service

    # Access cookies directly from the websocket object. Safari may instead
    # supply a short-lived signed ws_token in the query string.
    auth_refresh_token = websocket.cookies.get("auth_refresh_token")
    verified_ws_hash: str | None = None

    if not auth_refresh_token:
        # Fallback to query parameter for browsers that don't send cookies in WebSocket upgrade requests.
        # This is primarily for Safari on iOS which has issues sending httponly cookies in WebSocket connections.
        # SECURITY: The query param now contains a short-lived HMAC ws_token (format: token_hash:expiry:sig),
        # NOT the raw refresh token. We verify the HMAC and extract the token_hash to look up the session.
        ws_token_param = websocket.query_params.get("token")
        if ws_token_param:
            logger.debug("WebSocket auth: Token in query params — verifying as HMAC ws_token")
            verified_token_hash = verify_ws_token(ws_token_param)
            if verified_token_hash:
                logger.debug("WebSocket auth: HMAC ws_token verified")
                # Look up session data directly using the token_hash from the verified ws_token
                session_cache_key = f"{cache_service.SESSION_KEY_PREFIX}{verified_token_hash}"
                session_data = await cache_service.get(session_cache_key)
                if session_data:
                    # Only this verified signature may select the cache link.
                    verified_ws_hash = verified_token_hash
                else:
                    logger.warning("WebSocket auth: Session not found in cache after ws_token verification")
            else:
                logger.warning("WebSocket auth: Invalid signed ws_token")

    if not auth_refresh_token and verified_ws_hash is None:
        logger.warning("WebSocket connection denied: Missing 'auth_refresh_token' in both cookie and query parameters.")
        ComplianceService.log_auth_event_safe(
            event_type="ws_auth_failed",
            user_id=None,
            device_fingerprint="unknown",
            location="",
            status="failed",
            details={"reason": "missing_token"}
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        # Return None to signal authentication failure - connection already closed, no need to raise
        return None

    try:
        # 1. Get user data from cache using the extracted token
        # Only a verified signature in this request may select a session hash.
        # A caller-provided cookie that resembles an internal marker is raw
        # credential input and must never select a hash directly.
        if verified_ws_hash is not None:
            verified_hash = verified_ws_hash
            logger.debug("WebSocket auth: Using verified ws_token session")
            session_cache_key = f"{cache_service.SESSION_KEY_PREFIX}{verified_hash}"
            session_data = await cache_service.get(session_cache_key)
            pair_expires_at = await get_pair_deadline_hash(directus_service, cache_service, verified_hash)
            session_hash = verified_hash
        else:
            token_hash = hashlib.sha256(auth_refresh_token.encode()).hexdigest()
            session_cache_key = f"{cache_service.SESSION_KEY_PREFIX}{token_hash}"
            logger.debug("WebSocket auth: Looking for cookie session link")
            session_data = await cache_service.get(session_cache_key)
            pair_expires_at = await get_pair_deadline_hash(directus_service, cache_service, token_hash)
            session_hash = token_hash
        security_state = await get_session_state_cached(
            directus_service, cache_service, session_hash, allow_risk=False,
        )
        session_user_id = canonical_session_user_id(session_data)
        if security_state is not None and security_state.get("user_id") != session_user_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")
            return None
        cached_user_profile = (
            await cache_service.get_user_by_id(session_user_id) if session_user_id else None
        )
        user_data = dict(cached_user_profile) if isinstance(cached_user_profile, dict) else {}
        if session_user_id:
            user_data["user_id"] = session_user_id
        else:
            user_data = None
        logger.debug(f"WebSocket auth: Cache lookup result: {'Found' if user_data else 'Not Found'}")
        
        if not user_data:
            logger.warning("WebSocket connection denied: Invalid or expired token (not found in cache).")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")
            # Return None to signal authentication failure - connection already closed, no need to raise
            return None

        user_id = user_data.get("user_id")
        if not user_id:
            logger.error("WebSocket connection denied: User data in cache is invalid (missing user_id).")
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")
            # Return None to signal authentication failure - connection already closed, no need to raise
            return None

        if security_state is None:
            # A signed ws_token or cookie plus a matching cached session link
            # proves this pre-ledger session was already issued. Give it a fixed
            # durable deadline before admitting the connection.
            security_state = await ensure_legacy_session_hash_state(
                directus_service, cache_service, session_hash, user_id,
            )

        # 2. Extract sessionId from query parameters for browser instance uniqueness
        session_id = websocket.query_params.get("sessionId")
        if not session_id:
            logger.error(f"WebSocket auth: No sessionId provided for user {user_id}. SessionId is required for device fingerprint.")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session ID required")
            return None
        
        logger.debug("WebSocket auth: SessionId present")
        
        # 3. Generate TWO hashes for different purposes
        try:
            # - device_hash: Verify against known devices (security check)
            # - connection_hash: Identify this specific browser instance (WebSocket routing)
            device_hash, connection_hash, _, _, _, _, _, _ = generate_device_fingerprint_hash(websocket, user_id, session_id)
            logger.debug(f"Calculated WebSocket fingerprints for user {user_id}: Device={device_hash[:8]}..., Connection={connection_hash[:8]}...")
        except Exception as e:
            logger.error(f"Error calculating WebSocket fingerprint for user {user_id}: {e}", exc_info=True)
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Fingerprint error")
            return None

        # 4. Verify DEVICE HASH with retry mechanism for potential race conditions
        max_retries = 5
        retry_delay_seconds = 0.3  # 300ms
        device_hash_recognized = False

        for attempt in range(max_retries):
            known_device_hashes = await directus_service.get_user_device_hashes(user_id)
            
            # Check if the DEVICE hash (without sessionId) matches any known device
            # This prevents spam "new device" emails on every login
            if device_hash in known_device_hashes:
                logger.debug(f"Device hash {device_hash[:8]}... recognized for user {user_id} on attempt {attempt + 1}.")
                device_hash_recognized = True
                break  # Exit loop on success
            
            logger.debug(f"Device hash {device_hash[:8]}... not yet found for user {user_id} on attempt {attempt + 1}/{max_retries}. Retrying in {retry_delay_seconds}s...")
            await asyncio.sleep(retry_delay_seconds)

        if not device_hash_recognized:
            logger.warning(f"WebSocket connection denied after {max_retries} retries: Unknown device hash {device_hash[:8]}... for user {user_id}.")
            ComplianceService.log_auth_event_safe(
                event_type="ws_auth_failed",
                user_id=user_id,
                device_fingerprint=device_hash,
                location="",
                status="failed",
                details={"reason": "device_mismatch"}
            )
            reason = "Device mismatch"
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
            return None

        # Bind later HTTP authorization to the device recorded for this exact
        # refresh-token session. HTTP and WebSocket clients can legitimately
        # expose different User-Agent strings (the CLI does), so the freshly
        # derived WebSocket fingerprint is unsuitable as a cross-transport
        # identity even though it remains useful for known-device admission.
        token_map = await cache_service.get(f"user_tokens:{user_id}") or {}
        session_metadata = token_map.get(session_hash) if isinstance(token_map, dict) else None
        session_device_hash = (
            session_metadata.get("device_hash") if isinstance(session_metadata, dict) else None
        )
        if not isinstance(session_device_hash, str) or not session_device_hash:
            session_device_hash = device_hash

        # Authentication successful, device known
        # Return CONNECTION HASH for WebSocket routing (allows multiple browser instances)
        logger.debug(f"WebSocket authenticated: User {user_id}, Device {device_hash[:8]}..., Connection {connection_hash[:8]}...")
        ComplianceService.log_auth_event_safe(
            event_type="ws_auth_success",
            user_id=user_id,
            device_fingerprint=device_hash,
            location="",
            status="success",
            details={}
        )
        return {"user_id": user_id, "device_fingerprint_hash": connection_hash,
                "stable_device_fingerprint_hash": session_device_hash, "user_data": user_data,
                "pair_expires_at": pair_expires_at, "session_hash": session_hash,
                "session_expires_at": security_state.get("expires_at") if security_state else None}

    except Exception as e:
        logger.error(f"Unexpected error during WebSocket authentication: {e}", exc_info=True)
        # Attempt to close gracefully before returning None
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Authentication error")
        except Exception:
            pass # Ignore errors during close after another error
        # Return None to signal authentication failure - connection already closed, no need to raise
        return None
