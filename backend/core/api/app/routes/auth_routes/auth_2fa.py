from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
import logging
import qrcode
import io
import base64
import secrets
import string
import json
from typing import List, Optional, Dict, Any

# Import schemas from dedicated schema file
from app.schemas.auth_2fa import (
    Setup2FARequest, Setup2FAResponse, Verify2FACodeRequest, Verify2FACodeResponse,
    BackupCodesResponse, ConfirmCodesStoredRequest, ConfirmCodesStoredResponse,
    Setup2FAProviderRequest, Setup2FAProviderResponse
)

from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService
from app.routes.auth_routes.auth_dependencies import (
    get_directus_service, 
    get_cache_service, 
    get_metrics_service, 
    get_compliance_service
)
from app.routes.auth_routes.auth_utils import verify_allowed_origin
from app.routes.auth_routes.auth_common import verify_authenticated_user, require_auth
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip

router = APIRouter()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# Helper function to generate backup codes
def generate_backup_codes(count=5, length=12):
    """Generate random backup codes with hyphens every 4 characters."""
    backup_codes = []
    for _ in range(count):
        chars = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
        # Insert hyphens every 4 characters
        formatted_code = '-'.join(chars[i:i+4] for i in range(0, len(chars), 4))
        backup_codes.append(formatted_code)
    return backup_codes


@router.post("/setup_2fa", response_model=Setup2FAResponse, dependencies=[Depends(verify_allowed_origin)])
async def setup_2fa(
    request: Request,
    setup_request: Setup2FARequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Setup 2FA for a user by generating a secret key and returning the QR code.
    """
    logger.info("Processing /setup_2fa request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return Setup2FAResponse(success=False, message="Not authenticated")
        
        # Extract user_id from user_data
        user_id = user_data.get("user_id")
        if not user_id:
            return Setup2FAResponse(success=False, message="User ID not found")
            
        # Use dedicated TFA method with user's token
        success, response_data, message = await directus_service.generate_2fa_secret(
            refresh_token, setup_request.password
        )
        
        if not success:
            logger.error(f"Failed to generate 2FA secret: {message}")
            return Setup2FAResponse(success=False, message="Failed to generate 2FA secret")
        
        secret = response_data.get("secret")
        otpauth_url = response_data.get("otpauth_url")
        
        if not secret or not otpauth_url:
            return Setup2FAResponse(success=False, message="Invalid response from Directus")
        
        # Generate QR code image
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(otpauth_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert QR code to base64 string for embedding in frontend
        buffered = io.BytesIO()
        img.save(buffered)
        qr_code_base64 = base64.b64encode(buffered.getvalue()).decode()
        qr_code_url = f"data:image/png;base64,{qr_code_base64}"
        
        # Store the secret in cache temporarily (will be saved to the database when verified)
        await cache_service.set(f"2fa_setup:{user_id}", {
            "secret": secret,
            "otpauth_url": otpauth_url,
            "setup_complete": False
        }, ttl=3600)  # 1 hour expiry for setup completion
        
        # Log 2FA setup attempt for compliance (IP address + User ID required)
        client_ip = get_client_ip(request)
        compliance_service.log_auth_event(
            event_type="2fa_setup_initiated",
            user_id=user_id,
            ip_address=client_ip,
            status="initiated"
        )
        
        # Track successful 2FA setup attempt
        metrics_service.track_api_request("POST", "/v1/auth/setup_2fa", 200)
        
        return Setup2FAResponse(
            success=True,
            message="2FA setup initiated successfully",
            secret=secret,
            qr_code_url=qr_code_url,
            otpauth_url=otpauth_url
        )
        
    except Exception as e:
        logger.error(f"Error in setup_2fa: {str(e)}", exc_info=True)
        # Track failed 2FA setup attempt
        metrics_service.track_api_request("POST", "/v1/auth/setup_2fa", 500)
        return Setup2FAResponse(success=False, message="An error occurred during 2FA setup")


@router.post("/verify_2fa_code", response_model=Verify2FACodeResponse, dependencies=[Depends(verify_allowed_origin)])
async def verify_2fa_code(
    request: Request,
    verify_request: Verify2FACodeRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Verify a 2FA code during signup process or login.
    This endpoint detects whether the request comes from signup or login flow and
    updates the user data accordingly.
    """
    logger.info("Processing /verify_2fa_code request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return Verify2FACodeResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Get 2FA setup data from cache
        setup_data = await cache_service.get(f"2fa_setup:{user_id}")
        if not setup_data:
            return Verify2FACodeResponse(success=False, message="2FA setup not initiated")
        
        # Use dedicated TFA method with user's token
        success, response_data, message = await directus_service.enable_2fa(
            refresh_token, setup_data["secret"], verify_request.code
        )
        
        if not success:
            client_ip = get_client_ip(request)
            compliance_service.log_auth_event(
                event_type="2fa_verification",
                user_id=user_id,
                ip_address=client_ip,
                status="failed"
            )
            # Track failed 2FA verification attempt
            metrics_service.track_api_request("POST", "/v1/auth/verify_2fa_code", 400)
            return Verify2FACodeResponse(success=False, message="Invalid verification code")
        
        # Log successful verification
        client_ip = get_client_ip(request)
        compliance_service.log_auth_event(
            event_type="2fa_verification",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )
        # Track successful 2FA verification attempt
        metrics_service.track_api_request("POST", "/v1/auth/verify_2fa_code", 200)
        
        # Check if this is part of signup (not login)
        is_signup = user_data.get("last_opened", "").startswith("/signup")
        
        if is_signup:
            # Generate backup codes for the user
            backup_codes = generate_backup_codes()
            
            # Store backup codes in cache (will be saved to DB when confirmed stored)
            await cache_service.set(f"2fa_backup_codes:{user_id}", backup_codes, ttl=3600)  # 1 hour expiry
            
            # Update setup data in cache to mark as complete
            setup_data["setup_complete"] = True
            await cache_service.set(f"2fa_setup:{user_id}", setup_data, ttl=3600)
            
            # 2FA is now enabled through the Directus endpoint above
            # Just update last_opened to proceed to next step
            success, _, message = await directus_service.update_user(user_id, {
                "last_opened": "/signup/step-5"  # Update last_opened to indicate step 5
            })
            
            if not success:
                logger.error(f"Failed to update user 2FA settings: {message}")
                return Verify2FACodeResponse(success=False, message="Failed to save 2FA settings")
            
            # Update cache with new signup step and last_opened
            user_data["last_opened"] = "/signup/step-5"
            await cache_service.set_user(user_data, refresh_token=refresh_token)
        else:
            # This is a login flow
            # Just verify the code and continue (no need to update signup steps)
            logger.info("2FA verification successful during login")
        
        return Verify2FACodeResponse(success=True, message="Verification successful")
        
    except Exception as e:
        logger.error(f"Error in verify_2fa_code: {str(e)}", exc_info=True)
        # Track failed 2FA verification attempt
        metrics_service.track_api_request("POST", "/v1/auth/verify_2fa_code", 500)
        return Verify2FACodeResponse(success=False, message="An error occurred during 2FA verification")


@router.get("/request_backup_codes", response_model=BackupCodesResponse, dependencies=[Depends(verify_allowed_origin)])
async def request_backup_codes(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Generate and return backup codes for 2FA.
    """
    logger.info("Processing /request_backup_codes request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return BackupCodesResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Check if 2FA is set up and verified
        setup_data = await cache_service.get(f"2fa_setup:{user_id}")
        if not setup_data or not setup_data.get("setup_complete"):
            return BackupCodesResponse(success=False, message="2FA setup not complete")
        
        # Get existing backup codes from cache
        backup_codes = await cache_service.get(f"2fa_backup_codes:{user_id}")
        
        # If no backup codes exist in cache, generate new ones
        if not backup_codes:
            backup_codes = generate_backup_codes()
            await cache_service.set(f"2fa_backup_codes:{user_id}", backup_codes, ttl=3600)  # 1 hour expiry
        
        # Log backup codes request for compliance
        client_ip = get_client_ip(request)
        compliance_service.log_auth_event(
            event_type="2fa_backup_codes_requested",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )
        
        # Track successful backup codes request
        metrics_service.track_api_request("GET", "/v1/auth/request_backup_codes", 200)
        
        return BackupCodesResponse(
            success=True,
            message="Backup codes generated successfully",
            backup_codes=backup_codes
        )
        
    except Exception as e:
        logger.error(f"Error in request_backup_codes: {str(e)}", exc_info=True)
        # Track failed backup codes request
        metrics_service.track_api_request("GET", "/v1/auth/request_backup_codes", 500)
        return BackupCodesResponse(success=False, message="An error occurred while generating backup codes")


@router.post("/confirm_codes_stored", response_model=ConfirmCodesStoredResponse, dependencies=[Depends(verify_allowed_origin)])
async def confirm_codes_stored(
    request: Request,
    confirm_request: ConfirmCodesStoredRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Confirm that the user has stored their backup codes.
    """
    logger.info("Processing /confirm_codes_stored request")
    
    try:
        if not confirm_request.confirmed:
            return ConfirmCodesStoredResponse(
                success=False, 
                message="You must confirm that you have stored your backup codes"
            )
        
        # Verify user authentication using shared function
        is_auth, user_data, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return ConfirmCodesStoredResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Get backup codes from cache
        backup_codes = await cache_service.get(f"2fa_backup_codes:{user_id}")
        if not backup_codes:
            return ConfirmCodesStoredResponse(success=False, message="No backup codes found")
        
        # Hash backup codes for secure storage
        import hashlib
        hashed_codes = [
            hashlib.sha256(code.encode('utf-8')).hexdigest()
            for code in backup_codes
        ]
        
        # Update user in Directus to store hashed backup codes
        success, _, message = await directus_service.update_user(user_id, {
            "tfa_backup_codes": hashed_codes,
            "signup_complete": True  # Mark signup as complete
        })
        
        if not success:
            logger.error(f"Failed to update user with backup codes: {message}")
            return ConfirmCodesStoredResponse(success=False, message="Failed to save backup codes")
        
        # Clear backup codes from cache for security
        await cache_service.delete(f"2fa_backup_codes:{user_id}")
        
        # Log confirmation for compliance
        client_ip = get_client_ip(request)
        compliance_service.log_auth_event(
            event_type="2fa_setup_complete",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )
        
        # Track successful 2FA setup completion
        metrics_service.track_api_request("POST", "/v1/auth/confirm_codes_stored", 200)
        
        return ConfirmCodesStoredResponse(
            success=True,
            message="Backup codes confirmed and stored successfully"
        )
        
    except Exception as e:
        logger.error(f"Error in confirm_codes_stored: {str(e)}", exc_info=True)
        # Track failed 2FA setup completion
        metrics_service.track_api_request("POST", "/v1/auth/confirm_codes_stored", 500)
        return ConfirmCodesStoredResponse(success=False, message="An error occurred while confirming backup codes")


@router.post("/setup_2fa_provider", response_model=Setup2FAProviderResponse, dependencies=[Depends(verify_allowed_origin)])
async def setup_2fa_provider(
    request: Request,
    provider_request: Setup2FAProviderRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Save which 2FA provider was used by the user.
    """
    logger.info("Processing /setup_2fa_provider request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return Setup2FAProviderResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Validate provider
        valid_providers = [
            "Google Authenticator",
            "Microsoft Authenticator",
            "Authy",
            "1Password",
            "LastPass",
            "OTP Auth",
            "Other"
        ]
        
        if provider_request.provider not in valid_providers:
            return Setup2FAProviderResponse(
                success=False, 
                message=f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
            )
        
        # Update user in Directus to store the 2FA provider
        success, _, message = await directus_service.update_user(user_id, {
            "tfa_provider": provider_request.provider
        })
        
        if not success:
            logger.error(f"Failed to update user 2FA provider: {message}")
            return Setup2FAProviderResponse(success=False, message="Failed to save 2FA provider")
        
        return Setup2FAProviderResponse(
            success=True,
            message="2FA provider saved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error in setup_2fa_provider: {str(e)}", exc_info=True)
        return Setup2FAProviderResponse(success=False, message="An error occurred while saving 2FA provider")