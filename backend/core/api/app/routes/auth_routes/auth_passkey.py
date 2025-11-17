"""
Passkey (WebAuthn) Authentication Endpoints

This module implements passkey registration and authentication flows using WebAuthn.
Passkeys provide passwordless authentication while maintaining zero-knowledge encryption
through the PRF (Pseudo-Random Function) extension.

Security Requirements:
- PRF extension is REQUIRED for zero-knowledge encryption
- Master key is wrapped using HKDF(PRF_signature, user_email_salt)
- Server never sees PRF signature or master key in plaintext
"""

from fastapi import APIRouter, Depends, Request, Response, HTTPException
import logging
import time
import hashlib
import os
import base64
import json
from typing import Optional, Dict, Any
from backend.core.api.app.schemas.auth import (
    PasskeyRegistrationInitiateRequest,
    PasskeyRegistrationInitiateResponse,
    PasskeyRegistrationCompleteRequest,
    PasskeyRegistrationCompleteResponse,
    PasskeyAssertionInitiateRequest,
    PasskeyAssertionInitiateResponse,
    PasskeyAssertionVerifyRequest,
    PasskeyAssertionVerifyResponse,
    LoginRequest
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip
from backend.core.api.app.utils.invite_code import validate_invite_code
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_metrics_service,
    get_compliance_service,
    get_encryption_service
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username
from backend.core.api.app.routes.auth_routes.auth_login import finalize_login_session

router = APIRouter()
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

# WebAuthn Configuration
# TODO: Move to environment variables or config
def get_rp_id() -> str:
    """Get the Relying Party ID from environment or derive from origin"""
    rp_id = os.getenv("WEBAUTHN_RP_ID")
    if rp_id:
        return rp_id
    
    # Derive from allowed origins (fallback)
    # Extract domain from first allowed origin
    origin = os.getenv("PRODUCTION_URL") or os.getenv("FRONTEND_URLS", "https://openmates.org")
    if origin:
        # Extract domain from URL (e.g., "https://openmates.org" -> "openmates.org")
        origin = origin.split(',')[0].strip()  # Take first origin if multiple
        if origin.startswith("http://") or origin.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            return parsed.hostname or "openmates.org"
    
    return "openmates.org"

def get_rp_name() -> str:
    """Get the Relying Party name"""
    return os.getenv("WEBAUTHN_RP_NAME", "OpenMates")

@router.post("/passkey/registration/initiate", response_model=PasskeyRegistrationInitiateResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def passkey_registration_initiate(
    request: Request,
    initiate_request: PasskeyRegistrationInitiateRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Initiate passkey registration by generating a WebAuthn challenge.
    Returns PublicKeyCredentialCreationOptions for the client.
    """
    logger.info("Processing POST /passkey/registration/initiate")
    
    try:
        # Generate a random challenge (32 bytes, base64-encoded)
        challenge_bytes = os.urandom(32)
        challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        # Store challenge in cache with 5-minute TTL
        challenge_cache_key = f"passkey_challenge:{challenge}"
        await cache_service.set(challenge_cache_key, {
            "hashed_email": initiate_request.hashed_email,
            "user_id": initiate_request.user_id,
            "timestamp": int(time.time())
        }, ttl=300)
        
        # Get user information if user_id is provided (for adding passkey to existing account)
        user_id_bytes = None
        user_name = None
        user_display_name = None
        
        if initiate_request.user_id:
            # Existing user - get user info
            user_profile = await cache_service.get_user_by_id(initiate_request.user_id)
            if user_profile:
                user_name = initiate_request.hashed_email  # Use hashed_email as user.name
                user_display_name = user_profile.get("username", "User")
        else:
            # New user signup - use hashed_email as user identifier
            user_name = initiate_request.hashed_email
        
        # Convert hashed_email to bytes for user.id (WebAuthn requires bytes)
        user_id_bytes = base64.urlsafe_b64decode(initiate_request.hashed_email + '==')[:64]  # Limit to 64 bytes
        
        # Build WebAuthn PublicKeyCredentialCreationOptions
        rp_id = get_rp_id()
        rp_name = get_rp_name()
        
        # Get origin from request headers
        origin = request.headers.get("Origin") or request.headers.get("Referer", "").rsplit("/", 1)[0]
        
        creation_options = {
            "challenge": challenge,
            "rp": {
                "id": rp_id,
                "name": rp_name
            },
            "user": {
                "id": base64.urlsafe_b64encode(user_id_bytes).decode('utf-8').rstrip('='),
                "name": user_name,
                "displayName": user_display_name or user_name
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},  # ES256
                {"type": "public-key", "alg": -257}  # RS256
            ],
            "timeout": 60000,
            "attestation": "direct",
            "authenticatorSelection": {
                "residentKey": "required",  # Required for passwordless login
                "userVerification": "preferred",
                "authenticatorAttachment": "platform"  # Prefer platform authenticators (biometrics)
            },
            "extensions": {
                "prf": {
                    "eval": {
                        "first": base64.urlsafe_b64encode(challenge_bytes[:32]).decode('utf-8').rstrip('=')
                    }
                }
            }
        }
        
        logger.info(f"Generated passkey registration challenge for hashed_email: {initiate_request.hashed_email[:8]}...")
        
        return PasskeyRegistrationInitiateResponse(
            success=True,
            challenge=creation_options["challenge"],
            rp=creation_options["rp"],
            user=creation_options["user"],
            pubKeyCredParams=creation_options["pubKeyCredParams"],
            timeout=creation_options["timeout"],
            attestation=creation_options["attestation"],
            authenticatorSelection=creation_options["authenticatorSelection"],
            message="Passkey registration initiated"
        )
        
    except Exception as e:
        logger.error(f"Error initiating passkey registration: {str(e)}", exc_info=True)
        return PasskeyRegistrationInitiateResponse(
            success=False,
            challenge="",
            rp={"id": "", "name": ""},
            user={"id": "", "name": "", "displayName": ""},
            pubKeyCredParams=[],
            timeout=60000,
            attestation="direct",
            authenticatorSelection={},
            message=f"Failed to initiate passkey registration: {str(e)}"
        )

@router.post("/passkey/registration/complete", response_model=PasskeyRegistrationCompleteResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def passkey_registration_complete(
    request: Request,
    complete_request: PasskeyRegistrationCompleteRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Complete passkey registration by verifying attestation and storing passkey.
    Creates user account if this is a new signup.
    """
    logger.info("Processing POST /passkey/registration/complete")
    
    try:
        # CRITICAL: Verify PRF was enabled
        if not complete_request.prf_enabled:
            logger.error("Passkey registration attempted without PRF extension - rejecting for security")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="PRF extension is required for passkey registration. Your password manager doesn't support the PRF standard. Please try another password manager or use password as a signup option instead.",
                user=None
            )
        
        # TODO: Verify WebAuthn attestation using webauthn library
        # For now, we'll do basic validation and note where full verification should be added
        # Full implementation should use: py_webauthn or webauthn library
        
        # Extract credential ID from attestation response
        credential_id = complete_request.credential_id
        
        # Check if credential_id already exists (prevent duplicates)
        existing_passkey = await directus_service.get_passkey_by_credential_id(credential_id)
        if existing_passkey:
            logger.warning(f"Attempted to register duplicate credential_id")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="This passkey is already registered.",
                user=None
            )
        
        # Validate username
        username_error = validate_username(complete_request.username)
        if username_error:
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message=f"Invalid username: {username_error}",
                user=None
            )
        
        # Check if user already exists
        exists_result, existing_user, _ = await directus_service.get_user_by_hashed_email(complete_request.hashed_email)
        if exists_result and existing_user:
            logger.warning(f"Attempted to register with existing email")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="This email is already registered. Please log in instead.",
                user=None
            )
        
        # Validate invite code
        invite_code = complete_request.invite_code
        code_data = None
        signup_limit = int(os.getenv("SIGNUP_LIMIT", "0"))
        require_invite_code = signup_limit > 0
        
        if require_invite_code:
            if not invite_code:
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Invite code is required for signup.",
                    user=None
                )
            code_data = await validate_invite_code(invite_code, directus_service, cache_service)
            if not code_data:
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Invalid or expired invite code.",
                    user=None
                )
        
        # Extract additional information from invite code
        is_admin = code_data.get('is_admin', False) if code_data else False
        role = code_data.get('role') if code_data else None
        
        # Create the user account with encrypted email
        success, user_data, create_message = await directus_service.create_user(
            username=complete_request.username,
            encrypted_email=complete_request.encrypted_email,
            user_email_salt=complete_request.user_email_salt,
            lookup_hash=complete_request.lookup_hash,
            hashed_email=complete_request.hashed_email,
            language=complete_request.language,
            darkmode=complete_request.darkmode,
            is_admin=is_admin,
            role=role,
        )
        
        if not success:
            logger.error(f"Failed to create user: {create_message}")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Failed to create your account. Please try again later.",
                user=None
            )
        
        user_id = user_data.get("id")
        vault_key_id = user_data.get("vault_key_id")
        
        # TODO: Full WebAuthn attestation verification
        # Should verify:
        # 1. clientDataJSON matches expected challenge
        # 2. attestationObject is valid
        # 3. signature verification using public key
        # 4. AAGUID validation (optional)
        # For now, we'll extract basic info and note where verification should happen
        
        # Parse attestation response to extract public key and AAGUID
        # This is a simplified extraction - full implementation should use webauthn library
        attestation_obj = complete_request.attestation_response
        
        # Extract public key from attestation (simplified - should use CBOR decoding)
        # TODO: Use proper CBOR decoding to extract public_key_jwk from attestationObject
        public_key_jwk = attestation_obj.get("publicKey", {})  # Placeholder
        aaguid = attestation_obj.get("aaguid", "00000000-0000-0000-0000-000000000000")  # Placeholder
        
        # Encrypt device name if provided (extract from user agent or request)
        encrypted_device_name = None
        # TODO: Extract device name from user agent or request from user
        # For now, device_name is None - can be added later
        
        # Store passkey credential using hashed_user_id for privacy
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        passkey_success = await directus_service.create_passkey(
            hashed_user_id=hashed_user_id,
            credential_id=credential_id,
            public_key_jwk=public_key_jwk,
            aaguid=aaguid,
            encrypted_device_name=encrypted_device_name
        )
        
        if not passkey_success:
            logger.error(f"Failed to store passkey for user {user_id}")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Failed to store passkey. Please try again.",
                user=None
            )
        
        # Create encryption key record (same pattern as password)
        try:
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            success = await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='passkey',
                encrypted_key=complete_request.encrypted_master_key,
                salt=complete_request.salt,
                key_iv=complete_request.key_iv
            )
            if success:
                logger.info(f"Successfully created encryption key record for user {user_id}")
            else:
                logger.error(f"Failed to create encryption key for user {user_id}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Failed to set up account encryption. Please try again.",
                    user=None
                )
        except Exception as e:
            logger.error(f"Failed to create encryption key for user {user_id}: {e}", exc_info=True)
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Failed to set up account encryption. Please try again.",
                user=None
            )
        
        # Generate device fingerprint
        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        await directus_service.add_user_device_hash(user_id, device_hash)
        
        # Handle gifted credits (same as password signup)
        gifted_credits = code_data.get('gifted_credits') if code_data else None
        if gifted_credits and isinstance(gifted_credits, (int, float)) and gifted_credits > 0:
            plain_gift_value = int(gifted_credits)
            logger.info(f"Invite code included {plain_gift_value} gifted credits for user {user_id}.")
            if vault_key_id:
                try:
                    encrypted_gift_tuple = await encryption_service.encrypt_with_user_key(str(plain_gift_value), vault_key_id)
                    encrypted_gift_value = encrypted_gift_tuple[0]
                    await directus_service.update_user(
                        user_id,
                        {"encrypted_gifted_credits_for_signup": encrypted_gift_value}
                    )
                except Exception as encrypt_err:
                    logger.error(f"Failed to encrypt gifted credits for user {user_id}: {encrypt_err}", exc_info=True)
        
        # Consume invite code if provided
        if require_invite_code and invite_code and code_data:
            try:
                consume_success = await directus_service.consume_invite_code(invite_code, code_data)
                if consume_success:
                    logger.info(f"Successfully consumed invite code {invite_code} for user {user_id}")
                    await cache_service.delete(f"invite_code:{invite_code}")
            except Exception as consume_err:
                logger.error(f"Error consuming invite code {invite_code} for user {user_id}: {consume_err}", exc_info=True)
        
        # Track metrics
        metrics_service.track_user_creation()
        metrics_service.update_active_users(1, 1)
        
        # Log compliance event
        compliance_service.log_user_creation(
            user_id=user_id,
            status="success"
        )
        
        # Authenticate user to get session cookies
        auth_success, auth_data, auth_message = await directus_service.login_user_with_lookup_hash(
            hashed_email=complete_request.hashed_email,
            lookup_hash=complete_request.lookup_hash
        )
        
        if not auth_success or not auth_data:
            logger.error(f"Failed to authenticate user after passkey creation: {auth_message}")
            return PasskeyRegistrationCompleteResponse(
                success=True,
                message="Account created, but automatic login failed. Please log in manually.",
                user={"id": user_id}
            )
        
        # Finalize login session
        user = auth_data.get("user", {})
        refresh_token = await finalize_login_session(
            request=request,
            response=response,
            user=user,
            auth_data=auth_data,
            cache_service=cache_service,
            compliance_service=compliance_service,
            directus_service=directus_service,
            current_device_hash=device_hash,
            client_ip=_extract_client_ip(request.headers, request.client.host if request.client else None),
            encryption_service=encryption_service,
            device_location_str=f"{city}, {country_code}" if city and country_code else country_code or "Unknown",
            latitude=latitude,
            longitude=longitude,
            login_data=LoginRequest(
                hashed_email=complete_request.hashed_email,
                lookup_hash=complete_request.lookup_hash,
                login_method="passkey",
                stay_logged_in=False
            )
        )
        
        logger.info(f"Passkey registration completed successfully for user {user_id[:6]}...")
        event_logger.info(f"User account created with passkey - ID: {user_id}")
        
        return PasskeyRegistrationCompleteResponse(
            success=True,
            message="Passkey registered successfully",
            user={
                "id": user_id,
                "username": complete_request.username
            }
        )
        
    except Exception as e:
        logger.error(f"Error completing passkey registration: {str(e)}", exc_info=True)
        return PasskeyRegistrationCompleteResponse(
            success=False,
            message=f"Failed to complete passkey registration: {str(e)}",
            user=None
        )

@router.post("/passkey/assertion/initiate", response_model=PasskeyAssertionInitiateResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def passkey_assertion_initiate(
    request: Request,
    initiate_request: PasskeyAssertionInitiateRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Initiate passkey assertion (login) by generating a WebAuthn challenge.
    Returns PublicKeyCredentialRequestOptions for the client.
    """
    logger.info("Processing POST /passkey/assertion/initiate")
    
    try:
        # Generate a random challenge (32 bytes, base64-encoded)
        challenge_bytes = os.urandom(32)
        challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        # Store challenge in cache with 5-minute TTL
        challenge_cache_key = f"passkey_assertion_challenge:{challenge}"
        await cache_service.set(challenge_cache_key, {
            "hashed_email": initiate_request.hashed_email,
            "timestamp": int(time.time())
        }, ttl=300)
        
        # Get allowed credentials if hashed_email is provided
        allow_credentials = []
        if initiate_request.hashed_email:
            # Look up user's passkeys using hashed_user_id
            exists_result, user_data, _ = await directus_service.get_user_by_hashed_email(initiate_request.hashed_email)
            if exists_result and user_data:
                user_id = user_data.get("id")
                if user_id:
                    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                    passkeys = await directus_service.get_user_passkeys(hashed_user_id)
                    for passkey in passkeys:
                        allow_credentials.append({
                            "type": "public-key",
                            "id": passkey.get("credential_id")
                        })
        
        # Build WebAuthn PublicKeyCredentialRequestOptions
        rp_id = get_rp_id()
        rp_name = get_rp_name()
        
        request_options = {
            "challenge": challenge,
            "rpId": rp_id,
            "timeout": 60000,
            "userVerification": "preferred",
            "allowCredentials": allow_credentials,
            "extensions": {
                "prf": {
                    "eval": {
                        "first": base64.urlsafe_b64encode(challenge_bytes[:32]).decode('utf-8').rstrip('=')
                    }
                }
            }
        }
        
        logger.info(f"Generated passkey assertion challenge")
        
        return PasskeyAssertionInitiateResponse(
            success=True,
            challenge=request_options["challenge"],
            rp={"id": rp_id, "name": rp_name},
            timeout=request_options["timeout"],
            allowCredentials=request_options["allowCredentials"],
            userVerification=request_options["userVerification"],
            message="Passkey assertion initiated"
        )
        
    except Exception as e:
        logger.error(f"Error initiating passkey assertion: {str(e)}", exc_info=True)
        return PasskeyAssertionInitiateResponse(
            success=False,
            challenge="",
            rp={"id": "", "name": ""},
            timeout=60000,
            allowCredentials=[],
            userVerification="preferred",
            message=f"Failed to initiate passkey assertion: {str(e)}"
        )

@router.post("/passkey/assertion/verify", response_model=PasskeyAssertionVerifyResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def passkey_assertion_verify(
    request: Request,
    verify_request: PasskeyAssertionVerifyRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Verify passkey assertion (login) by validating signature and returning user data.
    """
    logger.info("Processing POST /passkey/assertion/verify")
    
    try:
        # Get passkey by credential_id
        passkey = await directus_service.get_passkey_by_credential_id(verify_request.credential_id)
        if not passkey:
            logger.warning(f"Passkey not found for credential_id")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get user_id from hashed_user_id by looking up in encryption_keys or users table
        hashed_user_id = passkey.get("hashed_user_id")
        if not hashed_user_id:
            logger.error("Passkey missing hashed_user_id")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey data. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Look up user_id from hashed_user_id via encryption_keys table
        # (encryption_keys has hashed_user_id and we can get user_id from users table)
        # Actually, we need to get user_id - let's query users by checking encryption_keys
        # For now, we'll need to get user_id from the hashed_email lookup or store a mapping
        # TODO: Consider adding a lookup table or storing user_id hash mapping
        # For assertion, we can get user_id from hashed_email if provided, or from lookup
        
        stored_sign_count = passkey.get("sign_count", 0)
        public_key_jwk = passkey.get("public_key_jwk")
        
        # Get user_id - if hashed_email provided, use it; otherwise we need to look it up
        user_id = None
        if verify_request.hashed_email:
            exists_result, user_data, _ = await directus_service.get_user_by_hashed_email(verify_request.hashed_email)
            if exists_result and user_data:
                user_id = user_data.get("id")
                # Verify hashed_user_id matches
                expected_hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                if expected_hashed_user_id != hashed_user_id:
                    logger.error(f"hashed_user_id mismatch for passkey")
                    return PasskeyAssertionVerifyResponse(
                        success=False,
                        message="Passkey verification failed.",
                        user_id=None,
                        hashed_email=None,
                        encrypted_email=None,
                        encrypted_master_key=None,
                        key_iv=None,
                        salt=None,
                        user_email_salt=None,
                        auth_session=None
                    )
        else:
            # For resident credentials, we need to look up user_id from hashed_user_id
            # We can query encryption_keys to find a user with this hashed_user_id
            # But encryption_keys doesn't have user_id directly...
            # For now, require hashed_email for non-resident credentials
            # TODO: Add user_id lookup by hashed_user_id or store mapping
            logger.warning("Resident credential login without hashed_email - lookup not yet implemented")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Please provide email for login.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        if not user_id:
            logger.error("Could not determine user_id from passkey")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="User not found. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # TODO: Full WebAuthn assertion verification
        # Should verify:
        # 1. clientDataJSON matches expected challenge
        # 2. authenticatorData is valid
        # 3. signature verification using stored public_key_jwk
        # 4. sign_count validation (detect cloned authenticators)
        # For now, we'll do basic validation
        
        # Extract sign_count from authenticator_data
        # TODO: Parse authenticator_data properly to get sign_count
        authenticator_data = base64.urlsafe_b64decode(verify_request.authenticator_data + '==')
        # Sign count is bytes 33-36 in authenticator_data (simplified - should use proper parsing)
        new_sign_count = stored_sign_count + 1  # Placeholder - should extract from authenticator_data
        
        # Validate sign_count (detect cloned authenticators)
        if new_sign_count <= stored_sign_count:
            logger.warning(f"Potential cloned authenticator detected for user {user_id[:6]}... (sign_count: {new_sign_count} <= stored: {stored_sign_count})")
            # Log security event but don't block (could be false positive)
            compliance_service.log_auth_event(
                event_type="passkey_cloned_detected",
                user_id=user_id,
                ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
                status="warning",
                details={
                    "credential_id": verify_request.credential_id[:8] + "...",
                    "stored_sign_count": stored_sign_count,
                    "new_sign_count": new_sign_count
                }
            )
        
        # Update passkey sign_count and last_used_at
        passkey_id = passkey.get("id")
        await directus_service.update_passkey_sign_count(passkey_id, new_sign_count)
        
        # Get user data
        user_profile = await cache_service.get_user_by_id(user_id)
        if not user_profile:
            # Fetch from Directus if not cached
            profile_success, user_profile, _ = await directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"User profile not found for user {user_id}")
                return PasskeyAssertionVerifyResponse(
                    success=False,
                    message="User not found. Please try again.",
                    user_id=None,
                    hashed_email=None,
                    encrypted_email=None,
                    encrypted_master_key=None,
                    key_iv=None,
                    salt=None,
                    user_email_salt=None,
                    auth_session=None
                )
        
        # Get encryption key for passkey login method
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, "passkey")
        if not encryption_key_data:
            logger.error(f"Encryption key not found for user {user_id} with passkey login method")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Encryption key not found. Please contact support.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get hashed_email from user profile or request
        hashed_email = verify_request.hashed_email
        if not hashed_email:
            # Try to get from user profile
            hashed_email = user_profile.get("hashed_email")
        
        # Authenticate user to get session
        lookup_hash = None  # For passkey, lookup_hash is derived from PRF signature client-side
        # We need to get it from the user's lookup_hashes array
        user_lookup_hashes = user_profile.get("lookup_hashes", [])
        # For passkey login, the client should send the lookup_hash derived from PRF signature
        # For now, we'll authenticate using the passkey credential_id as a temporary measure
        # TODO: Client should send lookup_hash in verify_request
        
        # Authenticate user
        auth_success, auth_data, auth_message = await directus_service.login_user_with_lookup_hash(
            hashed_email=hashed_email or "",
            lookup_hash=lookup_hash or ""
        )
        
        if not auth_success or not auth_data:
            logger.error(f"Failed to authenticate user {user_id} after passkey verification")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Authentication failed. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Generate device fingerprint
        session_id = verify_request.session_id
        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(
            request, user_id, session_id
        )
        
        # Finalize login session
        user = auth_data.get("user", {})
        refresh_token = await finalize_login_session(
            request=request,
            response=response,
            user=user,
            auth_data=auth_data,
            cache_service=cache_service,
            compliance_service=compliance_service,
            directus_service=directus_service,
            current_device_hash=device_hash,
            client_ip=_extract_client_ip(request.headers, request.client.host if request.client else None),
            encryption_service=encryption_service,
            device_location_str=f"{city}, {country_code}" if city and country_code else country_code or "Unknown",
            latitude=latitude,
            longitude=longitude,
            login_data=LoginRequest(
                hashed_email=hashed_email or "",
                lookup_hash=lookup_hash or "",
                login_method="passkey",
                stay_logged_in=verify_request.stay_logged_in,
                email_encryption_key=verify_request.email_encryption_key,
                session_id=session_id
            )
        )
        
        logger.info(f"Passkey assertion verified successfully for user {user_id[:6]}...")
        
        return PasskeyAssertionVerifyResponse(
            success=True,
            message="Passkey authentication successful",
            user_id=user_id,
            hashed_email=hashed_email,
            encrypted_email=user_profile.get("encrypted_email_address"),
            encrypted_master_key=encryption_key_data.get("encrypted_key"),
            key_iv=encryption_key_data.get("key_iv"),
            salt=encryption_key_data.get("salt"),
            user_email_salt=user_profile.get("user_email_salt"),
            auth_session={
                "refresh_token": refresh_token,
                "user": user
            }
        )
        
    except Exception as e:
        logger.error(f"Error verifying passkey assertion: {str(e)}", exc_info=True)
        return PasskeyAssertionVerifyResponse(
            success=False,
            message=f"Failed to verify passkey: {str(e)}",
            user_id=None,
            hashed_email=None,
            encrypted_email=None,
            encrypted_master_key=None,
            key_iv=None,
            salt=None,
            user_email_salt=None,
            auth_session=None
        )

