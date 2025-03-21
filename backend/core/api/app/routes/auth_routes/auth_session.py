from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import time
import hashlib
import json
from typing import Optional
from app.schemas.auth import SessionResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token")
):
    """
    Efficient session validation endpoint that uses cache to minimize Directus calls
    Returns session information if a valid session exists
    """
    logger.info("Processing session request")
    
    try:
        # Use either our renamed cookie or the original directus cookie
        refresh_token = refresh_token
        token_expiry = None
        
        if not refresh_token:
            logger.warning("No valid refresh token found in cookies")
            return SessionResponse(
                success=False,
                message="Not logged in",
                token_refresh_needed=False
            )
        
        # Get device fingerprint for validation
        device_fingerprint = get_device_fingerprint(request)
        logger.info(f"Device fingerprint: {device_fingerprint[:6]}...")
        
        # Don't get location immediately - only determine it if needed later for new devices
        device_location = None
        
        # Step 1: Try to get session data from cache
        # Hash the token for cache key to avoid storing raw tokens
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        cache_key = f"session:{token_hash}"
        user_key = f"user_token:{token_hash}"
        
        # Log the hash (partial) to help debug consistency
        logger.info(f"Session cache lookup with key hash: {token_hash[:6]}...")
        
        # Get session from cache
        cached_session = await cache_service.get(cache_key)
        
        if cached_session:
            logger.info("Found session in cache!")
            
            # Get user data from session
            user_id = cached_session.get("user_id")
            username = cached_session.get("username")
            is_admin = cached_session.get("is_admin", False)
            credits = cached_session.get("credits", 0)
            token_expiry = cached_session.get("token_expiry")
            vault_key_id = cached_session.get("vault_key_id")
            cached_devices = cached_session.get("devices", {})
            
            logger.info(f"Cached session for user: {username}, expires: {token_expiry}")
            
            # Check if this device is authorized
            device_authorized = device_fingerprint in cached_devices
            
            if not device_authorized:
                logger.warning(f"Device fingerprint not found in cached session devices")
                # Check in directus if device exists there but not in cache
                if user_id:
                    # For potentially new devices, get the location only when needed
                    if not device_location:
                        device_location = get_location_from_ip(get_client_ip(request))
                    
                    device_in_directus = await directus_service.check_user_device(user_id, device_fingerprint)
                    if device_in_directus:
                        # Device exists in Directus but not in cache, update cache
                        logger.info("Device found in Directus but not in cache, adding to cache")
                        current_time = int(time.time())
                        if not cached_devices:
                            cached_devices = {}
                        cached_devices[device_fingerprint] = {
                            "loc": device_location,
                            "first": current_time,
                            "recent": current_time
                        }
                        # Update session in cache
                        cached_session["devices"] = cached_devices
                        await cache_service.set(cache_key, cached_session, ttl=86400)
                        device_authorized = True
                
                if not device_authorized:
                    logger.warning("Device not authorized for this session")
                    # Don't clear session - it might be valid for other devices
                    return SessionResponse(
                        success=False,
                        message="Session not valid for this device",
                        token_refresh_needed=False
                    )
            
            # For authorized devices, retrieve location from cache instead of recalculating
            if device_fingerprint in cached_devices and not device_location:
                device_location = cached_devices[device_fingerprint].get("loc")
            
            # Check if token is about to expire (within 5 minutes)
            current_time = int(time.time())
            token_needs_refresh = False
            
            if token_expiry and token_expiry - current_time < 300:  # Less than 5 minutes left
                logger.info(f"Token expiry approaching (expires at {token_expiry}, now {current_time}), refreshing")
                token_needs_refresh = True
            
            # If token is still valid and not about to expire, return cached data
            if token_expiry and token_expiry > current_time and not token_needs_refresh:
                # Update last access time for the device
                if cached_devices and device_fingerprint in cached_devices:
                    cached_devices[device_fingerprint]["recent"] = current_time
                    # Update the cache with the new device access time
                    cached_session["devices"] = cached_devices
                    await cache_service.set(cache_key, cached_session, ttl=86400)  # Update with 24h TTL
                
                # Return success with cached user data
                logger.info("Using cached session data - token still valid")
                return SessionResponse(
                    success=True,
                    message="Session valid",
                    user={
                        "id": user_id,
                        "username": username,
                        "is_admin": is_admin,
                        "credits": credits,
                        "last_opened": cached_session.get("last_opened")
                    },
                    token_refresh_needed=False
                )
                
            # If token needs refresh, continue to the refresh process
            logger.info(f"Cache found but token needs refreshing (expiry: {token_expiry}, now: {current_time})")
        else:
            logger.info("No session found in cache, will refresh token")
                
        # Step 2: No valid cache or token needs refresh - check with Directus
        logger.info("Calling Directus refresh_token API...")
        success, auth_data, message = await directus_service.refresh_token(refresh_token)
        
        # If successful, cache the session data
        if success and auth_data and "user" in auth_data:
            user_data = auth_data["user"]
            user_id = user_data.get("id")
            username = user_data.get("username")
            is_admin = user_data.get("is_admin", False)
            vault_key_id = user_data.get("vault_key_id")
            
            # Get user's device information
            user_devices = {}
            encrypted_devices = user_data.get("encrypted_devices")
            
            if vault_key_id and encrypted_devices:
                try:
                    # Get encryption service from app state
                    encryption_service = request.app.state.encryption_service
                    
                    # Decrypt the devices data
                    decrypted_devices = await encryption_service.decrypt_with_user_key(
                        encrypted_devices, vault_key_id
                    )
                    user_devices = json.loads(decrypted_devices) if decrypted_devices else {}
                    
                    # Check if current device is in the user's devices
                    device_authorized = device_fingerprint in user_devices
                    
                    if not device_authorized:
                        logger.warning(f"Device fingerprint not found in user's devices")
                        # Only get location for new devices if we don't have it yet
                        if not device_location:
                            device_location = get_location_from_ip(get_client_ip(request))
                            
                        # Add device if not found since token is valid
                        current_time = int(time.time())
                        user_devices[device_fingerprint] = {
                            "loc": device_location,
                            "first": current_time,
                            "recent": current_time
                        }
                        
                        # Re-encrypt and update devices
                        encrypted_updated_devices, _ = await encryption_service.encrypt_with_user_key(
                            json.dumps(user_devices), vault_key_id
                        )
                        await directus_service.update_user_devices(user_id, encrypted_updated_devices)
                        logger.info(f"Added new device {device_fingerprint} to user devices")
                    else:
                        # Use existing location data from user_devices instead of recalculating
                        if not device_location:
                            device_location = user_devices[device_fingerprint].get("loc")
                        
                        # Update the last access time for the device
                        current_time = int(time.time())
                        user_devices[device_fingerprint]["recent"] = current_time
                        
                        # Re-encrypt and update devices
                        encrypted_updated_devices, _ = await encryption_service.encrypt_with_user_key(
                            json.dumps(user_devices), vault_key_id
                        )
                        await directus_service.update_user_devices(user_id, encrypted_updated_devices)
                        logger.info(f"Updated device {device_fingerprint} access time")
                    
                except Exception as e:
                    logger.error(f"Error processing devices: {str(e)}", exc_info=True)
                    # Continue with default empty devices if decryption fails
                    user_devices = {}
            
            # Get credits
            credits = 0
            try:
                if user_id:
                    credits = await directus_service.get_user_credits(user_id) 
            except Exception as e:
                logger.error(f"Error getting credits: {str(e)}")
            
            # Calculate token expiry time based on cookies
            cookies_dict = auth_data.get("cookies", {})
            # Assume token valid for 24 hours if we can't determine expiry
            token_expiry = int(time.time()) + 86400
            
            # Cache the session data with the NEW refresh token if provided
            new_refresh_token = None
            for name, value in cookies_dict.items():
                if name == "directus_refresh_token" or name == "auth_refresh_token":
                    new_refresh_token = value
                    break
                    
            # Use the new token for caching if available
            if new_refresh_token:
                # Update refresh_token to the new token
                refresh_token = new_refresh_token
                # Update the token hash for the cache key
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                cache_key = f"session:{token_hash}"
                user_key = f"user_token:{token_hash}"
                logger.info(f"Using new token for cache. Key hash: {token_hash[:6]}...{token_hash[-6:]}")
                
                # Remove old token from cache if present and different
                if cached_session and refresh_token != new_refresh_token:
                    old_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    old_cache_key = f"session:{old_token_hash}"
                    old_user_key = f"user_token:{old_token_hash}"
                    await cache_service.delete(old_cache_key)
                    await cache_service.delete(old_user_key)
                    logger.info(f"Deleted old token from cache: {old_token_hash[:6]}...{old_token_hash[-6:]}")
            
            # Cache the session data
            session_data = {
                "user_id": user_id,
                "username": username,
                "is_admin": is_admin,
                "credits": credits,
                "token_expiry": token_expiry,
                "vault_key_id": vault_key_id,
                "devices": user_devices,
                "last_opened": user_data.get("last_opened")
            }
            
            logger.info(f"Caching session data with TTL: 86400, expiry: {token_expiry}")
            await cache_service.set(cache_key, session_data, ttl=86400)  # 24 hour TTL
            
            # Link token to user id for logout handling
            await cache_service.set(user_key, user_id, ttl=86400)
            
            # Track all tokens for this user to enable logout-all functionality
            user_tokens_key = f"user_tokens:{user_id}"
            current_tokens = await cache_service.get(user_tokens_key) or {}
            current_tokens[token_hash] = {
                "device": device_fingerprint,
                "expiry": token_expiry
            }
            await cache_service.set(user_tokens_key, current_tokens, ttl=604800)  # 7 days
            
            # Save user_id to device mapping for quick lookups
            if user_id and device_fingerprint:
                await cache_service.set(
                    f"user_device:{user_id}:{device_fingerprint}", 
                    {
                        "loc": device_location, 
                        "first": user_devices.get(device_fingerprint, {}).get("first", int(time.time())),
                        "recent": int(time.time())
                    },
                    ttl=86400  # 24 hour cache
                )
            
            # Set new authentication cookies if received
            if "cookies" in auth_data and auth_data["cookies"]:
                for name, value in auth_data["cookies"].items():
                    # Rename cookies to use our prefix instead of directus prefix
                    cookie_name = name
                    if name.startswith("directus_"):
                        cookie_name = "auth_" + name[9:]  # Replace "directus_" with "auth_"
                        
                    response.set_cookie(
                        key=cookie_name,
                        value=value,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        max_age=86400  # 24 hours
                    )
            
            # Return success with user information
            return SessionResponse(
                success=True,
                message="Session authenticated",
                user={
                    "id": user_id,
                    "username": username,
                    "is_admin": is_admin,
                    "credits": credits,
                    "last_opened": user_data.get("last_opened")
                },
                token_refresh_needed=False
            )
        elif success and auth_data:
            # This is the case where we have cached user data but not a full fresh token
            user_data = auth_data.get("user", {})
            
            if user_data:
                # Return the cached user data we have
                return SessionResponse(
                    success=True,
                    message="Using cached session data",
                    user=user_data,
                    token_refresh_needed=True  # Client should try a full refresh soon
                )
            
        # If we get here, session is invalid
        return SessionResponse(
            success=False,
            message="Not logged in",
            token_refresh_needed=False
        )
            
    except Exception as e:
        logger.error(f"Error checking session: {str(e)}", exc_info=True)
        return SessionResponse(
            success=False,
            message="Session error",
            token_refresh_needed=False
        )
