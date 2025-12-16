from fastapi import APIRouter, Depends, Request, Response, status
import logging
import time
import hashlib
import base64
import json
import pyotp # Added for 2FA verification
import os # For generating random bytes and environment detection
from backend.core.api.app.schemas.auth import LoginRequest, LoginResponse, UserLookupRequest, UserLookupResponse
from backend.core.api.app.schemas.user import UserResponse # Added for constructing partial user response
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from typing import Optional
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip, get_geo_data_from_ip, parse_user_agent # Updated imports
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service, get_cache_service, get_metrics_service,
    get_compliance_service, get_encryption_service
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, get_cookie_domain
# Import backup code verification and hashing utilities
# Use sha_hash for cache, hash_backup_code (Argon2) for storage, verify_backup_code (Argon2) for verification
from backend.core.api.app.routes.auth_routes.auth_2fa_utils import verify_backup_code, sha_hash_backup_code
# Import Celery app instance and specific task
from backend.core.api.app.tasks.celery_config import app # General Celery app
# Import recovery key email task
from backend.core.api.app.tasks.email_tasks.recovery_key_email_task import send_recovery_key_used_email

"""
Zero-Knowledge Authentication System
-----------------------------------
This module implements a zero-knowledge authentication system where:

1. Email addresses are encrypted client-side and only decrypted temporarily when needed
2. The server never sees plaintext email encryption keys
3. Email encryption keys are derived client-side as: SHA256(email + user_email_salt)
4. When the client needs to decrypt an email, it sends the derived key with the request
5. The server uses this client-provided key for temporary decryption operations

This approach ensures that even if the server is compromised, email addresses remain protected
since the decryption keys are never stored on the server.
"""

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/login", response_model=LoginResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("3/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
):
    """
    Authenticate a user, handle 2FA if enabled, and create a session.
    Accepts optional tfa_code for the second step of 2FA login.
    """
    logger.info(f"Processing POST /login")
    
    try:
        # Step 1: Check if hashed_email and lookup_hash are provided
        if not login_data.hashed_email or not login_data.lookup_hash:
            logger.warning("Login attempt without required hashed_email or lookup_hash")
            return LoginResponse(success=False, message="Invalid login request: missing required parameters")
        
        # Step 2: Authenticate user with hashed_email and lookup_hash
        auth_success, auth_data, message = await directus_service.login_user_with_lookup_hash(
            hashed_email=login_data.hashed_email,
            lookup_hash=login_data.lookup_hash
        )
        
        # Check if this is a recovery key login
        is_recovery_key_login = login_data.login_method == "recovery_key"
        if is_recovery_key_login:
            logger.info(f"Recovery key login detected from request")
        
        metrics_service.track_login_attempt(auth_success)
        
        if not auth_success or not auth_data:
            # SECURITY: Prevent email enumeration by always pretending account exists
            # This prevents attackers from determining which email addresses have accounts
            
            # SECURITY: For recovery key login, always return the same response regardless of account existence
            # This ensures attackers cannot distinguish between non-existent accounts and wrong recovery keys
            # We do NOT check for user existence here to avoid timing differences that could leak information
            if is_recovery_key_login:
                logger.info("Recovery key authentication failed - returning generic error to prevent enumeration")
                # Return the exact same error response as if account exists but key was wrong
                # This must be identical in all aspects (message, timing, structure) to prevent enumeration
                return LoginResponse(
                    success=False, 
                    message="login.recovery_key_wrong.text"  # Same message for both non-existent and wrong key
                )
            
            # For password login, we can still log failed attempts (but only after checking if it's recovery key)
            # Log failed authentication attempt (but don't reveal account existence to client)
            temp_client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
            temp_user_agent = request.headers.get("User-Agent", "unknown")
            _, _, temp_os_name, _, _ = parse_user_agent(temp_user_agent)
            temp_geo_data = get_geo_data_from_ip(temp_client_ip)
            temp_country_code = temp_geo_data.get("country_code", "Unknown")
            temp_fingerprint_string = f"{temp_os_name}:{temp_country_code}:unknown_user" # Use "unknown_user" as salt
            temp_stable_hash = hashlib.sha256(temp_fingerprint_string.encode()).hexdigest()
            temp_device_location_str = f"{temp_geo_data.get('city')}, {temp_geo_data.get('country_code')}" if temp_geo_data.get('city') and temp_geo_data.get('country_code') else temp_geo_data.get('country_code') or "Unknown"

            # Try to get user ID for logging if possible using hashed_email (only for password login)
            exists_result, user_data_for_log, _ = await directus_service.get_user_by_hashed_email(login_data.hashed_email)
            if exists_result and user_data_for_log:
                compliance_service.log_auth_event(
                    event_type="login_failed", 
                    user_id=user_data_for_log.get("id"),
                    ip_address=temp_client_ip,
                    status="failed",
                    details={
                        "reason": "invalid_credentials",
                        "device_fingerprint_stable_hash": temp_stable_hash, # Log stable hash
                        "ip_address": temp_client_ip,
                        "location": temp_device_location_str
                    }
                )
            
            # SECURITY: For password login, always return tfa_required=True to prevent email enumeration
            # This makes the frontend show the 2FA input, regardless of whether account exists
            # If no 2FA code is provided, return the 2FA required response
            # Check for both None and empty string to handle edge cases
            # CRITICAL: Return tfa_enabled=False in anti-enumeration response so frontend knows
            # 2FA is not actually configured and can redirect to signup if needed
            if not login_data.tfa_code or login_data.tfa_code.strip() == "":
                logger.info("Authentication failed - returning tfa_required=True to prevent email enumeration")
                minimal_user_info = UserResponse(
                    username="",  # Default empty string
                    is_admin=False, # Default False
                    credits=0,      # Default 0
                    profile_image_url=None, # Optional field
                    tfa_app_name=None, # No specific app name (generic 2FA setup)
                    last_opened=None, # Don't reveal last_opened for non-existent accounts
                    tfa_enabled=False # Return False so frontend knows 2FA is not actually configured
                )
                response = LoginResponse(
                    success=True,
                    message="2FA required", 
                    tfa_required=True,
                    user=minimal_user_info
                )
                logger.debug(f"Returning LoginResponse: success={response.success}, tfa_required={response.tfa_required}, tfa_enabled={response.user.tfa_enabled}, message={response.message}")
                return response
            
            # If 2FA code was provided but authentication failed, return generic error
            # This handles the case where attacker tries to brute force 2FA codes
            # We don't reveal whether the account exists or not
            logger.info("Authentication failed with 2FA code provided - returning generic error to prevent enumeration")
            return LoginResponse(
                success=False, 
                message="login.code_wrong.text", 
                tfa_required=True  # Keep them on 2FA screen
            )
            
        # Authentication successful
        # Get user data from auth_data
        user = auth_data.get("user", {})
        user_id = user.get("id")
        if not user_id:
            logger.error("User ID missing after successful password validation.")
            return LoginResponse(success=False, message="Internal server error: User ID missing.")

        # Generate device fingerprint hashes
        # - device_hash: For device detection and "new device" emails (without sessionId)
        # - connection_hash: For WebSocket connection management (with sessionId)
        session_id = login_data.session_id
        if not session_id:
            logger.warning(f"Login attempt without session_id for user {user_id[:6]}...")
            return LoginResponse(success=False, message="Session ID required for login")
        logger.debug(f"Login: SessionId: {session_id[:8]}... for user {user_id[:6]}...")

        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id, session_id)
        # Store device_hash (without sessionId) in Directus for "new device" detection
        # This prevents spam emails on every login from the same physical device
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown" # More detailed location string

        # User profile should already be cached from /lookup endpoint
        user_profile = await cache_service.get_user_by_id(user_id)
        if not user_profile:
            logger.error(f"User profile not found in cache for user {user_id}. This should have been cached during /lookup.")
            return LoginResponse(success=False, message="User profile not found. Please try logging in again.")
        
        logger.info(f"Using cached user profile for login: {user_id}")
        
        # Merge profile into user object for consistency
        user.update(user_profile)
        auth_data["user"] = user # Ensure auth_data has the full profile

        # tfa_enabled is now included directly in the profile from get_user_profile
        tfa_enabled = user_profile.get("tfa_enabled", False)
        
        # CRITICAL: Verify that encrypted_tfa_secret actually exists before requiring 2FA
        # This prevents requiring 2FA when user hasn't completed setup during signup
        # The profile might have stale cache data, so we double-check the actual secret existence
        if tfa_enabled:
            # Verify encrypted_tfa_secret exists by checking if it's in the cached TFA data or fetching directly
            # This ensures we don't require 2FA if the secret was never created
            tfa_cache_key = f"user_tfa_data:{user_id}"
            cached_tfa_data = await cache_service.get(tfa_cache_key)
            encrypted_tfa_secret_exists = False
            
            if cached_tfa_data and cached_tfa_data.get("encrypted_tfa_secret"):
                encrypted_tfa_secret_exists = True
                logger.debug(f"User {user_id[:6]}... Found encrypted_tfa_secret in TFA cache")
            else:
                # Fallback: fetch directly from Directus to verify
                try:
                    user_fields = await directus_service.get_user_fields_direct(user_id, ["encrypted_tfa_secret"])
                    encrypted_tfa_secret_exists = bool(user_fields and user_fields.get("encrypted_tfa_secret"))
                    logger.debug(f"User {user_id[:6]}... Fetched encrypted_tfa_secret from Directus: {encrypted_tfa_secret_exists}")
                except Exception as e:
                    logger.warning(f"User {user_id[:6]}... Error verifying encrypted_tfa_secret: {e}")
                    # If we can't verify, err on the side of caution and disable 2FA requirement
                    encrypted_tfa_secret_exists = False
            
            if not encrypted_tfa_secret_exists:
                logger.warning(f"User {user_id[:6]}... Profile says tfa_enabled=True but encrypted_tfa_secret doesn't exist. Disabling 2FA requirement.")
                tfa_enabled = False
        
        logger.info(f"User {user_id[:6]}... Correctly read 2FA enabled status: {tfa_enabled}")

        user_profile["consent_privacy_and_apps_default_settings"] = bool(user_profile.get("consent_privacy_and_apps_default_settings"))
        user_profile["consent_mates_default_settings"] = bool(user_profile.get("consent_mates_default_settings"))

        # --- Scenario 1: 2FA Not Enabled OR Recovery Key Login OR Passkey Login ---
        # Recovery keys and Passkeys bypass 2FA as they are standalone/strong authentication methods
        is_passkey_login = login_data.login_method == "passkey"
        
        if not tfa_enabled or is_recovery_key_login or is_passkey_login:
            if is_recovery_key_login:
                logger.info("Recovery key login detected - bypassing 2FA and proceeding with login finalization.")
            elif is_passkey_login:
                logger.info("Passkey login detected - bypassing 2FA and proceeding with login finalization.")
            else:
                logger.info("2FA not enabled, proceeding with standard login finalization.")
            # Finalize login (set cookies, cache user, etc.)
            refresh_token = await finalize_login_session(
                    request=request,
                    response=response,
                    user=user,
                    auth_data=auth_data,
                    cache_service=cache_service,
                    compliance_service=compliance_service,
                    directus_service=directus_service,
                    current_device_hash=device_hash, # Pass the new device hash
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service,
                    device_location_str=device_location_str, # Pass location string
                    latitude=latitude, # Pass latitude
                    longitude=longitude, # Pass longitude
                    login_data=login_data # Pass login_data for email_encryption_key
                )
            if refresh_token:
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                logger.debug(f"[WS_TOKEN_DEBUG] finalize_login_session returned refresh_token (no 2FA path): hash={token_hash[:16]}...")

            # Send recovery key used notification if this was a recovery key login
            if is_recovery_key_login:
                try:
                    # Decrypt email address using client-provided key (zero-knowledge approach)
                    encrypted_email_address = user.get("encrypted_email_address")
                    decrypted_email = None
                    
                    if encrypted_email_address and login_data.email_encryption_key:
                        logger.info(f"Attempting to decrypt email for user {user_id[:6]}... using client-provided key for recovery key notification.")
                        try:
                            decrypted_email = await encryption_service.decrypt_with_email_key(
                                encrypted_email_address,
                                login_data.email_encryption_key
                            )
                            if decrypted_email:
                                logger.info(f"Successfully decrypted email for user {user_id[:6]}... using client-provided key.")
                            else:
                                logger.error(f"Failed to decrypt email with client-provided key for user {user_id[:6]}...")
                        except Exception as decrypt_exc:
                            logger.error(f"Error decrypting email with client-provided key for user {user_id[:6]}...: {decrypt_exc}", exc_info=True)
                    else:
                        logger.error(f"Cannot send recovery key used email for user {user_id[:6]}...: Missing encrypted_email_address or client-provided email_encryption_key.")

                    # Get preferences
                    user_language = user.get("language", "en")
                    user_darkmode = user.get("darkmode", False)

                    # Dispatch task if email was decrypted
                    if decrypted_email:
                        logger.info(f"Dispatching recovery key used email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***)")
                        app.send_task(
                            name='app.tasks.email_tasks.recovery_key_email_task.send_recovery_key_used_email',
                            kwargs={
                                'email_address': decrypted_email,
                                'language': user_language,
                                'darkmode': user_darkmode
                            },
                            queue='email'
                        )
                        
                        # Log the recovery key usage event
                        compliance_service.log_auth_event(
                            event_type="login_success_recovery_key",
                            user_id=user_id,
                            ip_address=client_ip,
                            status="success",
                            details={
                                "device_fingerprint_stable_hash": device_hash,
                                "location": device_location_str
                            }
                        )
                except Exception as email_task_exc:
                    logger.error(f"Failed to dispatch recovery key used email task for user {user_id[:6]}: {email_task_exc}", exc_info=True)
                    # Log error but continue with login finalization
            
            # Get encryption key - use appropriate login method
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            # Use the login_method from the request if provided, otherwise default based on recovery_key flag
            if login_data.login_method:
                login_method_for_key = login_data.login_method
            elif is_recovery_key_login:
                login_method_for_key = "recovery_key"
            elif is_passkey_login:
                # For passkey login, we need to find the specific encryption key for this passkey
                # The login_method format is "passkey_{credential_id_hash}"
                # However, we don't have the credential_id here easily available in login_data
                # But for passkey login, the client already has the decrypted master key from the assertion verification step
                # So we might not strictly need to fetch it here if the client already has it
                # BUT, finalize_login_session might expect it in user_profile
                
                # Strategy: If it's passkey login, we try to find ANY valid passkey encryption key for this user
                # OR we rely on the fact that the client already has the key
                
                # Actually, for passkey login, the client sends the lookup_hash which is derived from the specific passkey
                # We can use this lookup_hash to find the correct encryption key if we stored it
                # But currently encryption_keys table doesn't store lookup_hash directly
                
                # Let's use a special handling for passkey:
                # If login_method is "passkey", we might need to fetch all encryption keys for this user
                # and find the one that matches? No, that's inefficient.
                
                # Better approach: The client should send the specific login_method string (e.g. "passkey_...")
                # if it knows it. But currently it sends just "passkey".
                
                # Wait, in auth_passkey.py:passkey_assertion_verify, we return the encrypted key to the client.
                # The client decrypts it.
                # Then the client calls /login.
                # Does the client need the encrypted key again in the /login response?
                # Yes, finalize_login_session puts it in the response.
                
                # If we can't easily find the specific key, maybe we can skip this check for passkey login
                # since the client already proved possession of the key by sending the correct lookup_hash?
                # The lookup_hash proves they derived the correct key.
                
                # Let's try to fetch the key using the generic "passkey" method first (backward compatibility)
                # If that fails, we might need to look up by other means or skip.
                # But wait, get_encryption_key filters by login_method.
                
                # If we skip fetching encryption_key_data for passkey login, user_profile won't have
                # encrypted_key, key_iv, salt.
                # The client might need these if it didn't cache them?
                # But for passkey flow, client gets them from /verify endpoint.
                
                # Let's assume for now that for "passkey" login method, we might not find a single unique key
                # if we just search for "passkey".
                # However, we can try to find *an* encryption key if we really need to return one.
                
                # Ideally, we should update get_encryption_key to handle "passkey" by returning *any* valid passkey key
                # or the one matching the current session if possible.
                
                # For now, let's set login_method_for_key to "passkey" but handle the case where it returns nothing gracefully
                login_method_for_key = "passkey"
            else:
                login_method_for_key = "password"
            
            logger.debug(f"Using login_method '{login_method_for_key}' for encryption key lookup (requested: {login_data.login_method})")
            
            # Special handling for passkey: if generic "passkey" lookup fails, it might be because
            # keys are stored as "passkey_{hash}". We'll handle this in get_encryption_key or here.
            
            # If credential_id is provided (for passkey login), use it to find the specific key
            if is_passkey_login and login_data.credential_id:
                credential_id_hash = hashlib.sha256(login_data.credential_id.encode()).hexdigest()
                specific_login_method = f"passkey_{credential_id_hash}"
                logger.debug(f"Looking up specific encryption key for passkey: {specific_login_method}")
                encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, specific_login_method)
            else:
                encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, login_method_for_key)
            
            # If not found and it's a passkey login, try to find ANY passkey encryption key
            # This is a fallback to ensure we return *some* valid key data, though strictly speaking
            # the client already has the key from the verify step.
            if not encryption_key_data and is_passkey_login:
                logger.info(f"Specific passkey key not found, looking for any passkey keys for user {user_id}")
                # We need a new method in directus service to find any passkey encryption key
                # or we can just skip this if we decide it's not critical for /login response in passkey flow
                encryption_key_data = await directus_service.get_any_passkey_encryption_key(hashed_user_id)
            
            if not encryption_key_data:
                if is_passkey_login:
                    logger.warning(f"Encryption key not found for user {user_id} with login method {login_method_for_key}. Continuing anyway as client likely has key from verify step.")
                    # Don't fail login for passkey if key not found here, as client already has it
                else:
                    logger.error(f"Encryption key not found for user {user_id} with login method {login_method_for_key}. Login failed.")
                    return LoginResponse(success=False, message="Login failed. Please try again later.")
            
            if encryption_key_data:
                user_profile.update(encryption_key_data)
            
            # Dispatch warm_user_cache task if not already primed (fallback - should have started in /lookup)
            last_opened_path = user_profile.get("last_opened") # This is last_opened_path_from_user_model
            if user_id:
                cache_primed = await cache_service.is_user_cache_primed(user_id)
                if not cache_primed:
                    logger.info(f"[FALLBACK] User cache not primed for {user_id[:6]}... (should have been started in /lookup). Dispatching warm_user_cache task.")
                    if app.conf.task_always_eager is False: # Check if not running eagerly for tests
                        logger.info(f"Dispatching warm_user_cache task for user {user_id[:6]}... with last_opened_path: {last_opened_path}")
                        app.send_task(
                            name='app.tasks.user_cache_tasks.warm_user_cache', # Full path to the task
                            kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path},
                            queue='user_init' # Optional: specify a queue
                        )
                        # CRITICAL: Don't set primed flag here - let the cache warming task set it when complete!
                    elif app.conf.task_always_eager:
                        logger.info(f"Celery is in eager mode. warm_user_cache for user {user_id[:6]}... would run synchronously. Setting primed flag.")
                        # In eager mode, the task would run here. We can set the flag.
                        await cache_service.set_user_cache_primed_flag(user_id)
                    else: # Should not happen if user_id is present, but defensive
                        logger.error(f"Cannot dispatch warm_user_cache task: user_id is missing, though it was checked.")
                else:
                    logger.info(f"User cache already primed/warming for {user_id[:6]}... ✅")
            else:
                logger.error(f"Cannot dispatch warm_user_cache task or check primed status: user_id is missing.")


            if refresh_token:
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                logger.debug(f"[WS_TOKEN_DEBUG] Returning login response (no 2FA path) with ws_token: hash={token_hash[:16]}...")
            return LoginResponse(
                success=True,
                message="Login successful",
                user=UserResponse(
                    username=user_profile.get("username"),
                    is_admin=user_profile.get("is_admin", False),
                    credits=user_profile.get("credits", 0),
                    profile_image_url=user_profile.get("profile_image_url"),
                    last_opened=last_opened_path, # Already included
                    tfa_app_name=user_profile.get("tfa_app_name"),
                    tfa_enabled=user_profile.get("tfa_enabled", False),
                    consent_privacy_and_apps_default_settings=bool(user_profile.get("consent_privacy_and_apps_default_settings")),
                    consent_mates_default_settings=bool(user_profile.get("consent_mates_default_settings")),
                    language=user_profile.get("language", 'en'),
                    darkmode=user_profile.get("darkmode", False),
                    encrypted_key=user_profile.get("encrypted_key"),
                    key_iv=user_profile.get("key_iv"),
                    salt=user_profile.get("salt"),
                    user_email_salt=user_profile.get("user_email_salt")
                ),
                ws_token=refresh_token  # Return token for WebSocket auth (Safari iOS compatibility)
            )

        # --- 2FA IS Enabled ---
        
        # --- Scenario 2: 2FA Enabled, Code NOT Provided (First Step) ---
        if not login_data.tfa_code:
            logger.info("2FA enabled, code not provided. Returning tfa_required=True.")
            # Return minimal user info needed for the 2FA screen, using valid defaults for required fields
            # Include last_opened so frontend can redirect to signup if 2FA isn't actually configured
            minimal_user_info = UserResponse(
                username="",  # Default empty string
                is_admin=False, # Default False
                credits=0,      # Default 0
                profile_image_url=None, # Optional field
                tfa_app_name=user_profile.get("tfa_app_name"), # Send app name if available
                last_opened=user_profile.get("last_opened"), # Include last_opened for signup flow detection
                tfa_enabled=True # Explicitly set required field
            )
            return LoginResponse(
                success=True,
                message="2FA required", 
                tfa_required=True,
                user=minimal_user_info
            )
            
        # --- Scenario 3: 2FA Enabled, Code IS Provided (Second Step) ---
        logger.info(f"2FA enabled, code provided. Verifying code type: {login_data.code_type}...")
        
        # Ensure tfa_code is provided if we reach this stage
        if not login_data.tfa_code:
             logger.warning(f"2FA code missing in request for user {user_id} despite tfa_required being implied.")
             return LoginResponse(success=False, message="login.code_required.text", tfa_required=True)

        try:
            # --- Sub-Scenario 3a: Verify using OTP Code ---
            if login_data.code_type == "otp":
                logger.info(f"Verifying OTP code for user {user_id}...")
                
                # CACHE-FIRST: Try to get TFA data from dedicated TFA cache first
                tfa_cache_key = f"user_tfa_data:{user_id}"
                cached_tfa_data = await cache_service.get(tfa_cache_key)
                if cached_tfa_data:
                    encrypted_tfa_secret = cached_tfa_data.get("encrypted_tfa_secret")
                    vault_key_id = cached_tfa_data.get("vault_key_id")
                    logger.info(f"Using cached TFA data for user {user_id}")
                else:
                    # Fallback to direct fetch if not cached
                    logger.info(f"TFA data not cached, fetching directly for user {user_id}")
                    user_fields = await directus_service.get_user_fields_direct(
                        user_id, ["encrypted_tfa_secret", "vault_key_id"]
                    )
                    encrypted_tfa_secret = user_fields.get("encrypted_tfa_secret") if user_fields else None
                    vault_key_id = user_fields.get("vault_key_id") if user_fields else None
                    
                    # Cache the TFA data for future use (short TTL for security)
                    if encrypted_tfa_secret and vault_key_id:
                        tfa_data = {
                            "encrypted_tfa_secret": encrypted_tfa_secret,
                            "vault_key_id": vault_key_id
                        }
                        await cache_service.set(tfa_cache_key, tfa_data, ttl=300)  # 5 minutes TTL
                        logger.info(f"Cached TFA data for user {user_id}")

                if not encrypted_tfa_secret or not vault_key_id:
                    logger.error(f"Missing encrypted_tfa_secret or vault_key_id for user {user_id} during OTP verification.")
                    return LoginResponse(success=False, message="login.code_verification_error.text", tfa_required=True)

                # Decrypt the TFA secret
                try:
                    decrypted_secret = await encryption_service.decrypt_with_user_key(
                        encrypted_tfa_secret, vault_key_id
                    )
                except Exception as e:
                    logger.error(f"Failed to decrypt TFA secret for user {user_id}: {str(e)}", exc_info=True)
                    return LoginResponse(success=False, message="Error verifying 2FA code.", tfa_required=True)
                
                if not decrypted_secret:
                    # Handle cases where secret isn't found or decryption failed
                    logger.error(f"Could not retrieve or decrypt TFA secret for user {user_id} during OTP verification.")
                    # Don't reveal specific error, keep user on 2FA screen
                    return LoginResponse(success=False, message="login.code_verification_error.text", tfa_required=True)

                # Verify the code using the directly fetched secret
                totp = pyotp.TOTP(decrypted_secret)
                if not totp.verify(login_data.tfa_code):
                    logger.warning(f"Invalid OTP code provided for user {user_id}")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_otp_code",
                            "device_fingerprint_stable_hash": device_hash, # Log stable hash
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="login.code_wrong.text", tfa_required=True)
                
                # OTP Code is valid! Finalize the login.
                logger.info("OTP code verified successfully. Finalizing login.")
                refresh_token = await finalize_login_session(
                    request=request,
                    response=response,
                    user=user,
                    auth_data=auth_data,
                    cache_service=cache_service,
                    compliance_service=compliance_service,
                    directus_service=directus_service,
                    current_device_hash=device_hash, # Pass the new device hash
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service,
                    device_location_str=device_location_str, # Pass location string
                    latitude=latitude, # Pass latitude
                    longitude=longitude, # Pass longitude
                    login_data=login_data # Pass login_data for email_encryption_key
                )
                if refresh_token:
                    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    logger.debug(f"[WS_TOKEN_DEBUG] finalize_login_session returned refresh_token (OTP): hash={token_hash[:16]}...")

                # Get encryption key
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, "password")
                if not encryption_key_data:
                    logger.error(f"Encryption key not found for user {user_id}. Login failed.")
                    return LoginResponse(success=False, message="Login failed. Please try again later.")
                user_profile.update(encryption_key_data)

                # Dispatch warm_user_cache task if not already primed (fallback - should have started in /lookup)
                last_opened_path_otp = user_profile.get("last_opened")
                if user_id:
                    cache_primed_otp = await cache_service.is_user_cache_primed(user_id)
                    if not cache_primed_otp:
                        logger.info(f"[FALLBACK] User cache not primed for {user_id[:6]}... (OTP login - should have been started in /lookup). Dispatching warm_user_cache task.")
                        if app.conf.task_always_eager is False:
                            logger.info(f"Dispatching warm_user_cache task for user {user_id[:6]}... (OTP login) with last_opened_path: {last_opened_path_otp}")
                            app.send_task(
                                name='app.tasks.user_cache_tasks.warm_user_cache',
                                kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path_otp},
                                queue='user_init'
                            )
                            # CRITICAL: Don't set primed flag here - let the cache warming task set it when complete!
                        elif app.conf.task_always_eager:
                            logger.info(f"Celery is in eager mode. warm_user_cache for user {user_id[:6]}... (OTP login) would run synchronously. Setting primed flag.")
                            await cache_service.set_user_cache_primed_flag(user_id)
                        else: # Should not happen
                            logger.error(f"Cannot dispatch warm_user_cache task (OTP login): user_id is missing, though it was checked.")
                    else:
                        logger.info(f"User cache already primed/warming for {user_id[:6]}... (OTP login) ✅")
                else:
                    logger.error(f"Cannot dispatch warm_user_cache task or check primed status (OTP login): user_id is missing.")

                if refresh_token:
                    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    logger.debug(f"[WS_TOKEN_DEBUG] Returning login response (OTP) with ws_token: hash={token_hash[:16]}...")
                return LoginResponse(
                    success=True, message="Login successful",
                    user=UserResponse(
                        username=user_profile.get("username"),
                        is_admin=user_profile.get("is_admin", False),
                        credits=user_profile.get("credits", 0),
                        profile_image_url=user_profile.get("profile_image_url"),
                        last_opened=last_opened_path_otp,
                        tfa_app_name=user_profile.get("tfa_app_name"),
                        tfa_enabled=user_profile.get("tfa_enabled", False),
                        consent_privacy_and_apps_default_settings=bool(user_profile.get("consent_privacy_and_apps_default_settings")),
                        consent_mates_default_settings=bool(user_profile.get("consent_mates_default_settings")),
                        language=user_profile.get("language", 'en'),
                        darkmode=user_profile.get("darkmode", False),
                        encrypted_key=user_profile.get("encrypted_key"), # Pass encrypted_key
                        key_iv=user_profile.get("key_iv"), # Pass key_iv for Web Crypto API
                        salt=user_profile.get("salt"), # Pass salt
                        user_email_salt=user_profile.get("user_email_salt") # Pass user_email_salt
                    ),
                    ws_token=refresh_token  # Return token for WebSocket auth (Safari iOS compatibility)
                )

            # --- Sub-Scenario 3b: Verify using Backup Code ---
            elif login_data.code_type == "backup":
                logger.info(f"Verifying backup code for user {user_id}...")
                
                # Step 1: Calculate SHA256 hash of the provided code for cache operations
                try:
                    provided_code_sha_hash = sha_hash_backup_code(login_data.tfa_code)
                except Exception as e:
                    logger.error(f"Error SHA hashing provided backup code for user {user_id}: {e}", exc_info=True)
                    # Treat as invalid code if hashing fails
                    return LoginResponse(success=False, message="login.code_processing_error.text", tfa_required=True)

                # Step 2: Check cache for recently used backup code SHA hash (user-specific)
                used_code_cache_key = f"used_backup_code:{user_id}:{provided_code_sha_hash}"
                logger.info(f"Checking recently used backup code SHA hash...")
                recently_used = await cache_service.get(used_code_cache_key)

                if recently_used is not None:
                    logger.info(f"Backup code provided by user {user_id} matches a recently used code's SHA hash found in cache key.")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_backup_code_used",
                            "device_fingerprint_stable_hash": device_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="login.code_wrong.text", tfa_required=True)
                
                logger.info(f"Provided backup code's SHA hash not found in recently used cache for user {user_id}.")

                # Step 3: Fetch valid backup code Argon2 hashes from Directus
                hashed_codes_from_directus = await directus_service.get_tfa_backup_code_hashes(user_id)

                # Handle cases where hashes couldn't be fetched or parsed
                if hashed_codes_from_directus is None:
                     logger.error(f"Could not retrieve or parse backup code hashes from Directus for user {user_id}.")
                     return LoginResponse(success=False, message="login.code_verification_error.text", tfa_required=True)
                    
                # Check if list is empty (no codes configured or all used)
                if not hashed_codes_from_directus:
                    logger.warning(f"Backup code submitted for user {user_id}, but no backup codes found/remaining in Directus.")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_backup_code_none_remaining",
                            "device_fingerprint_stable_hash": device_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="login.no_backup_codes_remaining.text", tfa_required=True)

                # Step 4: Verify the plain text code against Directus Argon2 hashes
                logger.info(f"Attempting to verify plain text backup code against Directus Argon2 hashes. Provided code: '{login_data.tfa_code[:1]}***'") # Log only first char
                is_valid, matched_index = verify_backup_code(login_data.tfa_code, hashed_codes_from_directus)
                logger.info(f"Backup code verification result against Directus Argon2 hashes: {is_valid}, Matched index: {matched_index}")

                if not is_valid:
                    logger.warning(f"Invalid backup code provided for user {user_id} (did not match Directus hashes).")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_backup_code",
                            "device_fingerprint_stable_hash": device_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="login.code_wrong.text", tfa_required=True)

                # Step 5: Backup Code is valid! Add its SHA hash to Cache, Remove Argon2 hash from Directus, Finalize login.
                logger.info(f"Backup code verified successfully against Directus Argon2 hashes for user {user_id}. Processing...")
                
                # Step 5a: Add the SHA hash of the used code to the cache with a 30-minute TTL FIRST
                # Use the SHA hash calculated before the cache check (provided_code_sha_hash)
                # Use the same cache key format as the check (used_code_cache_key)
                logger.info(f"Adding used backup code's SHA hash to cache key '{used_code_cache_key}' with 30min TTL for user {user_id}.")
                
                # Set the user-specific used code key - CRITICAL: If this fails, stop processing.
                # TTL = 30 minutes = 1800 seconds
                cache_set_success = await cache_service.set(
                    used_code_cache_key, 
                    "used",  # Value doesn't matter, just needs to exist
                    ttl=1800 
                )
                if not cache_set_success:
                     logger.error(f"CRITICAL: Failed to set cache key '{used_code_cache_key}' for recently used backup code SHA hash for user {user_id}. Aborting login.")
                     # Return an error, preventing the code from being removed from Directus
                     return LoginResponse(
                         success=False,
                         message="login.security_state_update_failed.text",
                         tfa_required=True
                     )
                else:
                     logger.info(f"Successfully added used backup code's SHA hash to cache key '{used_code_cache_key}' for user {user_id}.")

                # Step 5b: Remove the used Argon2 hash from the list for Directus update
                # Use the matched_index from the Argon2 verification
                remaining_hashes_for_directus = [h for i, h in enumerate(hashed_codes_from_directus) if i != matched_index]
                remaining_count = len(remaining_hashes_for_directus) # Still useful for logging
                logger.info(f"Remaining backup codes count after removal: {remaining_count}")

                # Step 5c: Update Directus and WAIT for confirmation
                logger.info(f"Updating Directus for user {user_id} to remove used backup code hash.")
                update_directus_success = await directus_service.update_user(user_id, {
                    "tfa_backup_codes_hashes": remaining_hashes_for_directus
                })

                # Handle Directus update failure (Cache was already updated, but log this)
                if not update_directus_success:
                    logger.error(f"Failed to update backup codes in Directus for user {user_id} (Cache was updated).")
                    # Return an error and keep the user on the 2FA screen
                    return LoginResponse(
                        success=False,
                        message="login.backup_code_processing_failed.text",
                        tfa_required=True
                    )
                
                logger.info(f"Successfully updated backup codes in Directus for user {user_id}.")

                # --- Verification Complete ---
                
                # Step 5d: Send Backup Code Used Email Notification
                try:
                    # Anonymize the code (assuming format XXXX-XXXX-XXXX)
                    original_code = login_data.tfa_code
                    if len(original_code) == 14 and original_code[4] == '-' and original_code[9] == '-':
                         anonymized_code = f"{original_code[:10]}****"
                    else:
                         # Fallback if format is unexpected (log warning)
                         logger.warning(f"Backup code format unexpected for anonymization: '{original_code[:1]}***'. Using full code for anonymization fallback.")
                         anonymized_code = f"{original_code[:-4]}****" if len(original_code) > 4 else "****"

                    # Decrypt email address using only client-provided key (zero-knowledge approach)
                    encrypted_email_address = user.get("encrypted_email_address")
                    decrypted_email = None
                    
                    if encrypted_email_address and login_data.email_encryption_key:
                        logger.info(f"Attempting to decrypt email for user {user_id[:6]}... using client-provided key for backup code notification.")
                        try:
                            decrypted_email = await encryption_service.decrypt_with_email_key(
                                encrypted_email_address,
                                login_data.email_encryption_key
                            )
                            if decrypted_email:
                                logger.info(f"Successfully decrypted email for user {user_id[:6]}... using client-provided key.")
                            else:
                                logger.error(f"Failed to decrypt email with client-provided key for user {user_id[:6]}...")
                        except Exception as decrypt_exc:
                            logger.error(f"Error decrypting email with client-provided key for user {user_id[:6]}...: {decrypt_exc}", exc_info=True)
                    else:
                        logger.error(f"Cannot send backup code used email for user {user_id[:6]}...: Missing encrypted_email_address or client-provided email_encryption_key.")

                    # Get preferences
                    user_language = user.get("language", "en")
                    user_darkmode = user.get("darkmode", False)

                    # Dispatch task if email was decrypted
                    if decrypted_email:
                        logger.info(f"Dispatching backup code used email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***)")
                        app.send_task(
                            name='app.tasks.email_tasks.backup_code_email_task.send_backup_code_used_email',
                            kwargs={
                                'email_address': decrypted_email,
                                'anonymized_code': anonymized_code,
                                'language': user_language,
                                'darkmode': user_darkmode
                            },
                            queue='email'
                        )
                except Exception as email_task_exc:
                     logger.error(f"Failed to dispatch backup code used email task for user {user_id[:6]}: {email_task_exc}", exc_info=True)
                     # Log error but continue with login finalization

                # Step 5e: Log successful backup code use (Removed remaining count from details)
                compliance_service.log_auth_event(
                    event_type="login_success_backup_code", user_id=user_id, ip_address=client_ip,
                    status="success",
                    details={
                        "device_fingerprint_stable_hash": device_hash,
                        "location": device_location_str # Use derived location string
                    }
                )

                # Step 5f: Finalize the login session
                refresh_token = await finalize_login_session(
                    request=request,
                    response=response,
                    user=user,
                    auth_data=auth_data,
                    cache_service=cache_service,
                    compliance_service=compliance_service,
                    directus_service=directus_service,
                    current_device_hash=device_hash, # Pass the new device hash
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service,
                    device_location_str=device_location_str, # Pass location string
                    latitude=latitude, # Pass latitude
                    longitude=longitude, # Pass longitude
                    login_data=login_data # Pass login_data for email_encryption_key
                )
                if refresh_token:
                    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    logger.debug(f"[WS_TOKEN_DEBUG] finalize_login_session returned refresh_token (backup code): hash={token_hash[:16]}...")

                # Get encryption key
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, "password")
                if not encryption_key_data:
                    logger.error(f"Encryption key not found for user {user_id}. Login failed.")
                    return LoginResponse(success=False, message="Login failed. Please try again later.")
                user_profile.update(encryption_key_data)
                
                # Dispatch warm_user_cache task if not already primed (fallback - should have started in /lookup)
                last_opened_path_backup = user_profile.get("last_opened")
                if user_id:
                    cache_primed_backup = await cache_service.is_user_cache_primed(user_id)
                    if not cache_primed_backup:
                        logger.info(f"[FALLBACK] User cache not primed for {user_id[:6]}... (Backup code login - should have been started in /lookup). Dispatching warm_user_cache task.")
                        if app.conf.task_always_eager is False:
                            logger.info(f"Dispatching warm_user_cache task for user {user_id[:6]}... (Backup code login) with last_opened_path: {last_opened_path_backup}")
                            app.send_task(
                                name='app.tasks.user_cache_tasks.warm_user_cache',
                                kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path_backup},
                                queue='user_init'
                            )
                            # CRITICAL: Don't set primed flag here - let the cache warming task set it when complete!
                        elif app.conf.task_always_eager:
                            logger.info(f"Celery is in eager mode. warm_user_cache for user {user_id[:6]}... (Backup code login) would run synchronously. Setting primed flag.")
                            await cache_service.set_user_cache_primed_flag(user_id)
                        else: # Should not happen
                            logger.error(f"Cannot dispatch warm_user_cache task or check primed status (Backup code login): user_id is missing, though it was checked.")
                    else:
                        logger.info(f"User cache already primed/warming for {user_id[:6]}... (Backup code login) ✅")
                else:
                    logger.error(f"Cannot dispatch warm_user_cache task or check primed status (Backup code login): user_id is missing.")

                if refresh_token:
                    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    logger.debug(f"[WS_TOKEN_DEBUG] Returning login response (backup code) with ws_token: hash={token_hash[:16]}...")
                return LoginResponse(
                    success=True, message="Login successful using backup code",
                    user=UserResponse(
                        username=user_profile.get("username"),
                        is_admin=user_profile.get("is_admin", False),
                        credits=user_profile.get("credits", 0),
                        profile_image_url=user_profile.get("profile_image_url"),
                        last_opened=last_opened_path_backup,
                        tfa_app_name=user_profile.get("tfa_app_name"),
                        tfa_enabled=user_profile.get("tfa_enabled", False),
                        consent_privacy_and_apps_default_settings=bool(user_profile.get("consent_privacy_and_apps_default_settings")),
                        consent_mates_default_settings=bool(user_profile.get("consent_mates_default_settings")),
                        language=user_profile.get("language", 'en'),
                        darkmode=user_profile.get("darkmode", False),
                        encrypted_key=user_profile.get("encrypted_key"), # Pass encrypted_key
                        key_iv=user_profile.get("key_iv"), # Pass key_iv for Web Crypto API
                        salt=user_profile.get("salt"), # Pass salt
                        user_email_salt=user_profile.get("user_email_salt") # Pass user_email_salt
                    ),
                    ws_token=refresh_token  # Return token for WebSocket auth (Safari iOS compatibility)
                )

            # --- Sub-Scenario 3c: Invalid Code Type ---
            else:
                logger.warning(f"Invalid code_type '{login_data.code_type}' received for user {user_id}")
                return LoginResponse(success=False, message="Invalid request type.", tfa_required=True)

        except Exception as e:
            logger.error(f"Error during 2FA verification (type: {login_data.code_type}) for user {user_id}: {str(e)}", exc_info=True)
            return LoginResponse(
                success=False, 
                message="Error during 2FA verification", 
                tfa_required=True # Keep user on 2FA screen
            )

    except Exception as e:
        logger.error(f"Generic login error: {str(e)}", exc_info=True)
        return LoginResponse(success=False, message="An error occurred during login")


async def finalize_login_session(
    request: Request, # Added request parameter
    response: Response,
    user: dict,
    auth_data: dict,
    cache_service: CacheService,
    compliance_service: ComplianceService,
    directus_service: DirectusService,
    current_device_hash: str, # Changed: Pass the new device hash
    client_ip: str, # Pass IP for logging/notification context
    encryption_service: EncryptionService, # Added missing dependency
    device_location_str: str, # Added location string
    latitude: Optional[float], # Added latitude
    longitude: Optional[float], # Added longitude
    login_data: LoginRequest # Added login_data parameter for email_encryption_key
):
    """
    Helper function to perform common session finalization tasks:
    - Set cookies
    - Handle device tracking/logging
    - Cache user data
    
    Cookie expiration logic:
    - stay_logged_in=False: 24 hours (SESSION_TTL)
    - stay_logged_in=True: 30 days (for Safari iOS and mobile compatibility)
    """
    logger.info(f"Finalizing login session for user {user.get('id')[:6]}... (stay_logged_in={login_data.stay_logged_in})")
    refresh_token = None
    
    # Calculate cookie max_age based on stay_logged_in preference
    # 30 days = 2592000 seconds (for mobile Safari compatibility)
    # 24 hours = 86400 seconds (default SESSION_TTL)
    cookie_max_age = 2592000 if login_data.stay_logged_in else cache_service.SESSION_TTL
    logger.info(f"Setting cookies with max_age={cookie_max_age} seconds ({'30 days' if login_data.stay_logged_in else '24 hours'})")
    
    # Determine cookie domain for cross-subdomain authentication
    # Returns None for localhost (development), ".domain.com" for production subdomains
    cookie_domain = get_cookie_domain(request)
    if cookie_domain:
        logger.info(f"Setting cookies with domain={cookie_domain} for cross-subdomain authentication")
    
    # Determine if we should use secure cookies based on environment
    # Safari iOS strictly enforces that Secure=True cookies can ONLY be set over HTTPS
    # In development (localhost), we must set Secure=False to allow HTTP cookies
    is_dev = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"
    use_secure_cookies = not is_dev  # Only use Secure=True in production (HTTPS)
    
    if is_dev:
        logger.info("Development environment detected - using non-secure cookies for Safari iOS compatibility")
    
    # Set authentication cookies
    if "cookies" in auth_data:
        logger.info(f"Setting {len(auth_data['cookies'])} cookies")
        for name, value in auth_data["cookies"].items():
            if name == "directus_refresh_token":
                refresh_token = value
            cookie_name = name
            if name.startswith("directus_"):
                cookie_name = "auth_" + name[9:]
            
            # Build cookie parameters
            # Safari/iOS cookie requirements:
            # - SameSite=Lax works for same-site subdomains (app.domain.com <-> api.domain.com)
            # - Secure=True ONLY on HTTPS (Safari strictly enforces this)
            # - Secure=False on HTTP/localhost (development mode)
            # - Path=/ ensures cookie is available to all endpoints
            cookie_params = {
                "key": cookie_name,
                "value": value,
                "httponly": True,
                "secure": use_secure_cookies,  # False in dev (HTTP), True in prod (HTTPS)
                "samesite": "lax",  # Lax works for same-site subdomains (Safari compatible)
                "max_age": cookie_max_age,
                "path": "/"
            }

            # Only set domain parameter for cross-subdomain scenarios
            # This enables cookie sharing between app.domain.com and api.domain.com
            if cookie_domain:
                cookie_params["domain"] = cookie_domain

            response.set_cookie(**cookie_params)

    user_id = user.get("id")
    if user_id:
        # --- New Device Hash Handling ---
        logger.info(f"Checking device status for user {user_id[:6]}... with hash {current_device_hash[:8]}...")

        # Determine if this is a new device hash *before* adding it
        known_device_hashes = await directus_service.get_user_device_hashes(user_id)
        is_new_device_hash = current_device_hash not in known_device_hashes

        # Add the device hash to Directus (adds if new, does nothing if existing)
        update_success, update_msg = await directus_service.add_user_device_hash(user_id, current_device_hash)
        if not update_success:
            logger.error(f"Failed to add device hash for user {user_id}: {update_msg}")
            # Continue with login, but log the failure

        # If it's a new device hash, log and send notification
        if is_new_device_hash:
            logger.info(f"New device hash detected for user {user_id[:6]}...")
            # Log the event without IP to align with privacy policy (only failed attempts store IP)
            compliance_service.log_auth_event_safe(
                event_type="login_new_device",
                user_id=user_id,
                device_fingerprint=current_device_hash,
                location=device_location_str,
                status="success",
                details={}
            )

            # Send notification email about new device login via Celery
            try:
                user_language = user.get("language", "en")
                user_darkmode = user.get("darkmode", False)

                # Decrypt email using client-provided key (zero-knowledge approach)
                encrypted_email_address = user.get("encrypted_email_address")
                decrypted_email = None
                
                if encrypted_email_address and login_data.email_encryption_key:
                    logger.info(f"Attempting to decrypt email for user {user_id[:6]}... using client-provided key for new device notification.")
                    try:
                        decrypted_email = await encryption_service.decrypt_with_email_key(
                            encrypted_email_address,
                            login_data.email_encryption_key
                        )
                        if decrypted_email:
                            logger.info(f"Successfully decrypted email for user {user_id[:6]}... using client-provided key.")
                        else:
                            logger.error(f"Failed to decrypt email with client-provided key for user {user_id[:6]}...")
                    except Exception as decrypt_exc:
                        logger.error(f"Error decrypting email with client-provided key for user {user_id[:6]}...: {decrypt_exc}", exc_info=True)
                else:
                    logger.error(f"Cannot send new device email for user {user_id[:6]}...: Missing encrypted_email_address or client-provided email_encryption_key.")

                # Only send task if email was successfully decrypted
                if decrypted_email:
                    # Determine if IP was localhost based on fingerprint data
                    is_localhost = "Local" in device_location_str # Simple check based on location string

                    logger.info(f"Dispatching new device email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***) with location data.")
                    app.send_task(
                        name='app.tasks.email_tasks.new_device_email_task.send_new_device_email',
                        kwargs={
                            'email_address': decrypted_email,
                            'user_agent_string': request.headers.get("User-Agent", "unknown"), # Get user agent directly from request
                            'ip_address': client_ip, # Still send the actual IP used for lookup
                            'latitude': latitude, # Pass latitude
                            'longitude': longitude, # Pass longitude
                            'location_name': device_location_str, # Use the derived location string
                            'is_localhost': is_localhost,
                            'language': user_language,
                            'darkmode': user_darkmode
                        },
                        queue='email'
                    )
            except Exception as task_exc:
                logger.error(f"Failed to dispatch new device email task for user {user_id[:6]}: {task_exc}", exc_info=True)
        # --- End New Device Hash Handling ---

        # Update last online timestamp in Directus
        current_time = int(time.time()) # Define current_time here
        await directus_service.update_user(user_id, {"last_online_timestamp": str(current_time)})

        # Update cached user data with session info and manage tokens
        if refresh_token:
            # Use extended TTL for cache when stay_logged_in is True
            # This ensures the cache stays valid as long as the cookies
            cache_ttl = cookie_max_age if login_data.stay_logged_in else cache_service.SESSION_TTL
            
            # Get existing cached user data and update it with session info
            cached_user_data = await cache_service.get_user_by_id(user_id)
            if cached_user_data:
                # CRITICAL: Validate that required fields are present before updating cache
                # If username or vault_key_id are missing, this indicates a data integrity issue
                if not cached_user_data.get("username"):
                    logger.error(f"CRITICAL: Cannot update cache for user {user_id} - username is missing from cached data. This indicates a data integrity issue.")
                    # Don't update cache with incomplete data - let get_current_user handle the error
                elif not cached_user_data.get("vault_key_id"):
                    logger.error(f"CRITICAL: Cannot update cache for user {user_id} - vault_key_id is missing from cached data. This indicates a data integrity issue.")
                    # Don't update cache with incomplete data - let get_current_user handle the error
                else:
                    # Ensure user_id is always present in cached data (required for WebSocket auth)
                    if "user_id" not in cached_user_data:
                        cached_user_data["user_id"] = user_id
                    # Also ensure "id" is present for compatibility
                    if "id" not in cached_user_data:
                        cached_user_data["id"] = user_id
                    # Update last_online_timestamp in cached data
                    cached_user_data["last_online_timestamp"] = current_time
                    # Store stay_logged_in preference for session endpoint to use
                    cached_user_data["stay_logged_in"] = login_data.stay_logged_in
                    # CRITICAL: Preserve username and vault_key_id - don't overwrite with incomplete data from user parameter
                    # The user parameter might come from login_user_with_lookup_hash which could have incomplete data
                    # Update with any additional session data that might be needed
                    # Pass custom TTL to match cookie expiration
                    await cache_service.set_user(cached_user_data, refresh_token=refresh_token, ttl=cache_ttl)
                    logger.info(f"Updated cached user data with stay_logged_in={login_data.stay_logged_in} for user {user_id[:6]}...")
            else:
                # Cache entry doesn't exist - fetch user profile and create cache entry with stay_logged_in
                logger.warning(f"No cached user data found for user {user_id} during session finalization. Fetching profile to create cache entry.")
                profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
                if profile_success and user_profile:
                    # CRITICAL: Validate that required fields are present before caching
                    # If username or vault_key_id are missing, this indicates a data integrity issue
                    if not user_profile.get("username"):
                        logger.error(f"CRITICAL: Cannot cache user profile for user {user_id} - username is missing from profile. This indicates a data integrity issue.")
                        logger.error(f"Profile message: {profile_message}")
                        # Don't cache incomplete data - let get_current_user handle the error
                    elif not user_profile.get("vault_key_id"):
                        logger.error(f"CRITICAL: Cannot cache user profile for user {user_id} - vault_key_id is missing from profile. This indicates a data integrity issue.")
                        # Don't cache incomplete data - let get_current_user handle the error
                    else:
                        # Ensure stay_logged_in is set in the profile data
                        user_profile["stay_logged_in"] = login_data.stay_logged_in
                        user_profile["last_online_timestamp"] = current_time
                        # Ensure user_id is in the profile for set_user to work
                        if "user_id" not in user_profile and "id" in user_profile:
                            user_profile["user_id"] = user_profile["id"]
                        await cache_service.set_user(user_profile, refresh_token=refresh_token, ttl=cache_ttl)
                        logger.info(f"Created cache entry with stay_logged_in={login_data.stay_logged_in} for user {user_id[:6]}...")
                else:
                    logger.error(f"Failed to fetch user profile for user {user_id} during session finalization: {profile_message}. stay_logged_in preference may be lost.")

            # Manage refresh tokens with extended TTL
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            user_tokens_key = f"user_tokens:{user_id}"
            current_tokens = await cache_service.get(user_tokens_key) or {}
            current_tokens[token_hash] = int(time.time())
            # Token list TTL should be longer than individual session TTL
            token_list_ttl = cache_ttl * 7 if login_data.stay_logged_in else cache_service.SESSION_TTL * 7
            await cache_service.set(user_tokens_key, current_tokens, ttl=token_list_ttl)
            logger.info(f"Updated token list for user {user_id[:6]}... ({len(current_tokens)} active)")

    logger.info("Login session finalization complete.")
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        logger.debug(f"[WS_TOKEN_DEBUG] About to return refresh_token from finalize_login_session: hash={token_hash[:16]}...")
    return refresh_token  # Return refresh token for WebSocket auth (Safari iOS compatibility)


@router.post("/lookup", response_model=UserLookupResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("3/minute")
async def lookup_user(
    request: Request,
    lookup_data: UserLookupRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
):
    """
    Look up a user by hashed email and return available login methods.
    This is the first step in the new multi-step login flow.
    """
    logger.info(f"Processing POST /lookup")
    
    try:
        # Step 1: Check if hashed_email is provided
        if not lookup_data.hashed_email:
            logger.warning("Lookup attempt without required hashed_email")
            # Return error response since this is a client error
            return Response(
                content=json.dumps({"error": "Missing required parameter: hashed_email"}),
                media_type="application/json",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Step 2: Look up user by hashed_email
        exists_result, user_data, _ = await directus_service.get_user_by_hashed_email(lookup_data.hashed_email)
        
        # Log the lookup attempt for metrics
        metrics_service.track_login_attempt(exists_result)
        
        # Step 3: If user doesn't exist, return default response with random salt to prevent email enumeration
        if not exists_result or not user_data:
            logger.info("User not found in lookup, returning default response with random salt")
            # Generate a random salt for non-existent users to prevent email enumeration
            random_salt = base64.b64encode(os.urandom(16)).decode('utf-8')
            return UserLookupResponse(
                login_method="password",
                available_login_methods=["password","recovery_key"],
                user_email_salt=random_salt,
                stay_logged_in=lookup_data.stay_logged_in  # Echo back the preference even for non-existent users
            )
        
        # Step 4: Get user profile to access tfa_app_name (leverages existing cache)
        user_id = user_data.get("id")
        tfa_app_name = None
        
        if user_id:
            # Check if user profile is already cached
            cached_user_profile = await cache_service.get_user_by_id(user_id)
            if cached_user_profile:
                tfa_app_name = cached_user_profile.get("tfa_app_name")
                logger.info(f"Using cached user profile for tfa_app_name lookup: {user_id}")
            else:
                # Fetch user profile if not cached (will be cached by get_user_profile)
                profile_success, user_profile, _ = await directus_service.get_user_profile(user_id)
                if profile_success and user_profile:
                    tfa_app_name = user_profile.get("tfa_app_name")
                    logger.info(f"Fetched user profile for tfa_app_name lookup: {user_id}")
        
        # Step 5: Determine available login methods
        available_methods = []
        preferred_method = "password"  # Default to password
        
        # Get hashed_user_id for encryption_keys lookup
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest() if user_id else None
        
        if hashed_user_id:
            # Create a cache key for the user's login methods
            login_methods_cache_key = f"user:{hashed_user_id}:login_methods"
            
            # Try to get login methods from cache first
            cached_login_methods = await cache_service.get(login_methods_cache_key)
            login_methods = None
            
            if cached_login_methods:
                logger.info(f"Using cached login methods for user {user_id}")
                login_methods = cached_login_methods
            else:
                # Cache miss - get all encryption keys for this user to determine available login methods
                logger.info(f"Cache miss for login methods. Fetching from Directus for user {user_id}")
                params = {
                    "filter[hashed_user_id][_eq]": hashed_user_id,
                    "fields": "login_method"
                }
                
                try:
                    encryption_keys = await directus_service.get_items("encryption_keys", params)
                    
                    # Extract login methods from encryption keys
                    login_methods = [key.get("login_method") for key in encryption_keys if isinstance(key, dict) and key.get("login_method")]
                    
                    # Cache the login methods with a 1-hour TTL
                    if login_methods:
                        await cache_service.set(login_methods_cache_key, login_methods, ttl=3600)
                        logger.info(f"Cached login methods for user {user_id}")
                except Exception as e:
                    logger.error(f"Error fetching encryption keys for user {user_id}: {str(e)}", exc_info=True)
                    # Fall back to default methods if we can't get encryption keys
                    login_methods = []
            
            if login_methods:
                # Check for password first - prefer password over passkey for better UX
                # Users expect to enter password after email, not be forced into passkey
                has_password = any(method == "password" for method in login_methods)
                if has_password:
                    available_methods.append("password")
                    preferred_method = "password"  # Prefer password as default
                
                # Check for passkey - verify that actual passkeys exist in user_passkeys table
                # CRITICAL: Only add passkey to available methods if there are actual passkeys registered
                # This prevents showing passkey login when encryption key exists but passkey was deleted
                has_passkey_encryption_key = any(method.startswith("passkey") for method in login_methods)
                if has_passkey_encryption_key:
                    # Verify that there are actual passkeys in the user_passkeys table
                    try:
                        actual_passkeys = await directus_service.get_user_passkeys_by_user_id(user_id)
                        has_actual_passkeys = len(actual_passkeys) > 0
                        
                        if has_actual_passkeys:
                            # available_methods.append("passkey") # Removed as per user request - frontend handles passkey availability
                            # Only set as preferred if password is not available
                            if not has_password:
                                preferred_method = "passkey"
                            logger.info(f"User {user_id} has {len(actual_passkeys)} passkey(s) - passkey login available")
                        else:
                            logger.info(f"User {user_id} has passkey encryption key but no actual passkeys - passkey login not available")
                    except Exception as e:
                        logger.error(f"Error checking passkeys for user {user_id}: {e}", exc_info=True)
                        # If we can't verify, don't add passkey to avoid showing unavailable option
                
                # Check for security_key
                has_security_key = any(method.startswith("security_key") for method in login_methods)
                if has_security_key:
                    available_methods.append("security_key")
                    # Only set as preferred if password and passkey are not available
                    if not has_password and not has_passkey:
                        preferred_method = "security_key"
                
                # Check for recovery_key (always available as fallback, but not preferred)
                has_recovery_key = any(method == "recovery_key" for method in login_methods)
                if has_recovery_key:
                    available_methods.append("recovery_key")
                
                logger.info(f"Found login methods for user {user_id}: {login_methods}")
            else:
                # Fall back to default methods if no login methods found
                available_methods = ["password", "recovery_key"]
                logger.warning(f"No login methods found for user {user_id}, using default")
        
        logger.info(f"User lookup successful. Available methods: {available_methods}, preferred: {preferred_method}")
        
        # Get user_email_salt and cache complete user data for existing users
        user_email_salt = None
        if user_id:
            # Try to get from cached profile first
            if cached_user_profile and "user_email_salt" in cached_user_profile:
                user_email_salt = cached_user_profile.get("user_email_salt")
                logger.info(f"Using cached user_email_salt for user {user_id}")
            else:
                # Get user_email_salt from the user_data we already fetched
                user_email_salt = user_data.get("user_email_salt")
                
                if user_email_salt:
                    logger.info(f"Found user_email_salt in user data for user {user_id}")
                    
                    # Since we don't have cached profile, fetch and cache the complete user profile
                    # This is what finalize_login_session does - we're moving it here for efficiency
                    profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
                    if profile_success and user_profile:
                        # Add user_email_salt to the profile since get_user_profile doesn't include it
                        user_profile["user_email_salt"] = user_email_salt
                        
                        # Cache the user using the same logic as finalize_login_session
                        user_data_to_cache = {
                            "user_id": user_id,
                            "username": user_profile.get("username"),
                            "is_admin": user_profile.get("is_admin", False),
                            "credits": user_profile.get("credits", 0),
                            "profile_image_url": user_profile.get("profile_image_url"),
                            "tfa_app_name": user_profile.get("tfa_app_name"),
                            "tfa_enabled": user_profile.get("tfa_enabled", False),
                            "last_opened": user_profile.get("last_opened"),
                            "vault_key_id": user_profile.get("vault_key_id"),
                            "consent_privacy_and_apps_default_settings": user_profile.get("consent_privacy_and_apps_default_settings"),
                            "consent_mates_default_settings": user_profile.get("consent_mates_default_settings"),
                            "language": user_profile.get("language", "en"),
                            "darkmode": user_profile.get("darkmode", False),
                            "gifted_credits_for_signup": user_profile.get("gifted_credits_for_signup"),
                            "encrypted_email_address": user_profile.get("encrypted_email_address"),
                            "invoice_counter": user_profile.get("invoice_counter"),
                            "lookup_hashes": user_profile.get("lookup_hashes", []),
                            "account_id": user_data.get("account_id"),  # From the original user_data
                            "user_email_salt": user_email_salt,  # Include the salt we just fetched
                            # Monthly subscription fields (cleartext fields, not sensitive)
                            "stripe_customer_id": user_profile.get("stripe_customer_id"),
                            "stripe_subscription_id": user_profile.get("stripe_subscription_id"),
                            "subscription_status": user_profile.get("subscription_status"),
                            "subscription_credits": user_profile.get("subscription_credits"),
                            "subscription_currency": user_profile.get("subscription_currency"),
                            "next_billing_date": user_profile.get("next_billing_date"),
                            # Keep encrypted payment method ID encrypted
                            "encrypted_payment_method_id": user_profile.get("encrypted_payment_method_id"),
                            # Low balance auto top-up fields (cleartext configuration fields)
                            "auto_topup_low_balance_enabled": user_profile.get("auto_topup_low_balance_enabled", False),
                            "auto_topup_low_balance_threshold": user_profile.get("auto_topup_low_balance_threshold"),
                            "auto_topup_low_balance_amount": user_profile.get("auto_topup_low_balance_amount"),
                            "auto_topup_low_balance_currency": user_profile.get("auto_topup_low_balance_currency")
                        }
                        
                        # CACHE TFA DATA: Cache encrypted TFA secret for faster login
                        if user_profile.get("tfa_enabled", False):
                            try:
                                # Fetch TFA data directly from Directus
                                tfa_fields = await directus_service.get_user_fields_direct(
                                    user_id, ["encrypted_tfa_secret", "vault_key_id"]
                                )
                                if tfa_fields and tfa_fields.get("encrypted_tfa_secret") and tfa_fields.get("vault_key_id"):
                                    tfa_cache_key = f"user_tfa_data:{user_id}"
                                    tfa_data = {
                                        "encrypted_tfa_secret": tfa_fields.get("encrypted_tfa_secret"),
                                        "vault_key_id": tfa_fields.get("vault_key_id")
                                    }
                                    await cache_service.set(tfa_cache_key, tfa_data, ttl=300)  # 5 minutes TTL
                                    logger.info(f"Cached TFA data during lookup for user {user_id}")
                            except Exception as e:
                                logger.warning(f"Failed to cache TFA data during lookup for user {user_id}: {e}")
                                # Don't fail the lookup if TFA caching fails
                        
                        # Remove gifted_credits_for_signup if it's None or 0 before caching
                        if not user_data_to_cache.get("gifted_credits_for_signup"):
                            user_data_to_cache.pop("gifted_credits_for_signup", None)
                        
                        # Cache the user data (without refresh_token since this is just lookup)
                        await cache_service.set_user(user_data_to_cache)
                        logger.info(f"Cached complete user profile for user {user_id} during lookup")
                        
                        # Predictively warm user cache for instant login UX
                        # This loads phases 1-3 (last opened chat, recent chats, full sync) from Directus to Redis
                        # All data remains encrypted - server cannot decrypt without user's master key
                        cache_primed = await cache_service.is_user_cache_primed(user_id)
                        
                        if not cache_primed:
                            # Check if warming already in progress to avoid duplicate work
                            warming_flag = f"cache_warming_in_progress:{user_id}"
                            is_warming = await cache_service.get(warming_flag)
                            
                            if not is_warming:
                                # Set flag to prevent duplicate warming attempts (5 min TTL)
                                await cache_service.set(warming_flag, "warming", ttl=300)
                                
                                # Get last_opened for cache warming task
                                last_opened_path = user_profile.get("last_opened") if user_profile else None
                                
                                logger.info(f"[PREDICTIVE] Pre-warming cache for user {user_id[:6]}... from /lookup endpoint")
                                
                                # Dispatch async - doesn't block /lookup response
                                # By the time user enters password and clicks login, cache should be ready
                                app.send_task(
                                    name='app.tasks.user_cache_tasks.warm_user_cache',
                                    kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path},
                                    queue='user_init'
                                )
                            else:
                                logger.info(f"Cache warming already in progress for user {user_id[:6]}...")
                        else:
                            logger.info(f"User cache already primed for {user_id[:6]}... (skipping predictive warming)")
        
        # If we still couldn't get the salt, this indicates a data integrity issue
        if not user_email_salt:
            logger.error(f"CRITICAL: Could not retrieve user_email_salt for existing user {user_id}. This indicates a data integrity issue.")
            # Return error instead of random salt to prevent authentication bypass
            return Response(
                content=json.dumps({"error": "User data integrity issue. Please contact support."}),
                media_type="application/json",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Get tfa_enabled status from cached profile or compute it
        # CRITICAL: For existing users, compute actual tfa_enabled based on encrypted_tfa_secret existence
        # Only default to True for non-existent users (anti-enumeration)
        tfa_enabled = True  # Default to True for security (anti-enumeration for non-existent users)
        if user_id:
            # CRITICAL: Always verify encrypted_tfa_secret exists, even if cached profile says tfa_enabled=True
            # This prevents stale cache data from causing 2FA to be required when it's not actually set up
            encrypted_tfa_secret_exists = bool(user_data.get("encrypted_tfa_secret"))
            
            # Try to get from cached profile first (should be available now after caching above)
            current_cached_profile = await cache_service.get_user_by_id(user_id)
            if current_cached_profile and "tfa_enabled" in current_cached_profile:
                cached_tfa_enabled = current_cached_profile.get("tfa_enabled", False)
                # Use cached value only if encrypted_tfa_secret actually exists
                # This prevents stale cache from requiring 2FA when it's not set up
                tfa_enabled = cached_tfa_enabled if encrypted_tfa_secret_exists else False
                logger.info(f"Using cached tfa_enabled for user {user_id}: {tfa_enabled} (verified: encrypted_tfa_secret exists={encrypted_tfa_secret_exists})")
            else:
                # Fallback: compute based on encrypted_tfa_secret existence from user_data
                tfa_enabled = encrypted_tfa_secret_exists
                logger.info(f"Computed tfa_enabled for user {user_id} based on encrypted_tfa_secret: {tfa_enabled}")

        # Return the response with available login methods, tfa_app_name, user_email_salt, tfa_enabled, and stay_logged_in
        return UserLookupResponse(
            login_method=preferred_method,
            available_login_methods=available_methods,
            tfa_app_name=tfa_app_name,
            user_email_salt=user_email_salt,
            tfa_enabled=tfa_enabled,
            stay_logged_in=lookup_data.stay_logged_in  # Echo back the preference
        )
    
    except Exception as e:
        logger.error(f"Error during user lookup: {str(e)}", exc_info=True)
        # Generate random salt for error case
        random_salt_error = base64.b64encode(os.urandom(16)).decode('utf-8')
        # Return default response to prevent email enumeration
        return UserLookupResponse(
            login_method="password",
            available_login_methods=["password", "recovery_key"],
            user_email_salt=random_salt_error,
            tfa_enabled=True,
            stay_logged_in=False  # Default to False for security
        )
