"""
Account Recovery Endpoints

Handles account recovery for users who lose access to ALL login methods
(password, passkey, AND recovery key).

This is a LAST RESORT that performs a full account reset, deleting all
client-encrypted data (chats, settings, memories, embeds) while preserving
server-encrypted data (credits, username, subscription).

Users who have their recovery key should use "Login with recovery key" instead,
which preserves ALL data.

Security:
- Email verification required before any recovery action
- Rate limited to prevent abuse
- All actions logged for audit trail
"""

from fastapi import APIRouter, Depends, Request
import logging
import hashlib
import base64
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from backend.core.api.app.schemas.auth_recovery import (
    RecoveryRequestRequest,
    RecoveryRequestResponse,
    RecoveryVerifyRequest,
    RecoveryVerifyResponse,
    RecoveryFullResetRequest,
    RecoveryCompleteResponse,
    Recovery2FASetupRequest,
    Recovery2FASetupResponse,
    RecoveryCancelRequest,
)
from backend.core.api.app.routes.auth_routes.auth_2fa_utils import generate_2fa_secret
import pyotp
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_compliance_service,
    get_encryption_service,
    get_current_user,
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip
from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.services.session_security_state import revoke_all_user_sessions
from backend.core.api.app.services.password_v2 import KDF_ID, decode_key, seal_auth_key
from backend.core.api.app.routes.auth_routes.recovery_reset_state import (
    cancel_pending_reset_if_current,
    parse_recovery_due_at,
    retryable_reset_failure as _retryable_reset_failure,
)


# Router setup
router = APIRouter(
    prefix="/recovery",
    tags=["Auth - Account Recovery"],
    dependencies=[Depends(verify_allowed_origin)]
)

logger = logging.getLogger(__name__)
RECOVERY_DELAY = timedelta(hours=24)
RECOVERY_COLLECTION = "account_recovery_resets"


async def _pending_reset(directus_service: DirectusService, user_id: str):
    rows = await directus_service.get_items(
        RECOVERY_COLLECTION,
        params={"filter": {"user_id": {"_eq": user_id}, "state": {"_in": ["pending", "processing"]}}, "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    return rows[0] if rows else None


# ============================================================================
# Helper Functions
# ============================================================================

def _hash_email(email: str) -> str:
    """
    Hash email address using SHA256 for lookup.
    Must match the client-side hashing.
    """
    email_bytes = email.lower().strip().encode('utf-8')
    hashed = hashlib.sha256(email_bytes).digest()
    return base64.b64encode(hashed).decode('utf-8')


async def _delete_user_client_data(
    user_id: str,
    user_id_hash: str,
    directus_service: DirectusService,
    cache_service: CacheService
) -> bool:
    """
    Delete all client-encrypted data for a user (chats, settings, memories, embeds).
    Reuses the same logic from account deletion task.
    
    Args:
        user_id: User UUID
        user_id_hash: SHA256 hash of user_id
        directus_service: DirectusService instance
        cache_service: CacheService instance
        
    Returns:
        True if successful, False otherwise
    """
    try:
        async def delete_required(collection: str, item_id: str):
            if not await directus_service.delete_item(collection, item_id, admin_required=True):
                raise RuntimeError(f"Could not delete {collection} item")

        logger.info(f"[ACCOUNT_RESET] Deleting client data for user {user_id[:8]}...")
        
        # 1. Delete all chats, messages, and embeds
        deleted_chats = 0
        deleted_messages = 0
        deleted_embeds = 0
        
        try:
            # Get all chats for this user (using hashed_user_id)
            chats = await directus_service.get_items(
                "chats",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}},
                raise_on_error=True,
            )
            
            for chat in chats or []:
                chat_id = chat.get("id")
                if chat_id:
                    # Delete messages for this chat
                    messages = await directus_service.get_items(
                        "messages",
                        params={"filter": {"chat_id": {"_eq": chat_id}}},
                        raise_on_error=True,
                    )
                    for message in messages or []:
                        message_id = message.get("id")
                        if message_id:
                            await delete_required("messages", message_id)
                            deleted_messages += 1
                    
                    # Delete embeds for this chat (using hashed_chat_id)
                    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
                    embeds = await directus_service.get_items(
                        "embeds",
                        params={"filter": {"hashed_chat_id": {"_eq": hashed_chat_id}}},
                        raise_on_error=True,
                    )
                    for embed in embeds or []:
                        embed_id = embed.get("id")
                        if embed_id:
                            await delete_required("embeds", embed_id)
                            deleted_embeds += 1
                    
                    # Delete chat
                    await delete_required("chats", chat_id)
                    deleted_chats += 1
            
            # Also delete any orphaned embeds by hashed_user_id
            orphaned_embeds = await directus_service.get_items(
                "embeds",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}},
                raise_on_error=True,
            )
            for embed in orphaned_embeds or []:
                embed_id = embed.get("id")
                if embed_id:
                    await delete_required("embeds", embed_id)
                    deleted_embeds += 1
            
            logger.info(f"[ACCOUNT_RESET] Deleted {deleted_chats} chats, {deleted_messages} messages, {deleted_embeds} embeds")
        except Exception as e:
            logger.error(f"[ACCOUNT_RESET] Error deleting chats/messages/embeds: {e}", exc_info=True)
            return False
        
        # 2. Delete app memories
        deleted_app_data = 0
        try:
            app_settings = await directus_service.get_items(
                "app_settings_and_memories",
                params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}},
                raise_on_error=True,
            )
            for setting in app_settings or []:
                setting_id = setting.get("id")
                if setting_id:
                    await delete_required("app_settings_and_memories", setting_id)
                    deleted_app_data += 1
            
            logger.info(f"[ACCOUNT_RESET] Deleted {deleted_app_data} app settings/memories")
        except Exception as e:
            logger.error(f"[ACCOUNT_RESET] Error deleting app settings/memories: {e}", exc_info=True)
            return False
        
        # 3. Delete all passkeys. Existing key wrappers remain until replacement
        # credentials are safely stored, so a failed write cannot orphan login.
        try:
            passkeys = await directus_service.get_items(
                "user_passkeys",
                params={"filter": {"user_id": {"_eq": user_id}}},
                admin_required=True,
                raise_on_error=True,
            )
            for passkey in passkeys or []:
                passkey_id = passkey.get("id")
                if passkey_id:
                    await delete_required("user_passkeys", passkey_id)
            logger.info(f"[ACCOUNT_RESET] Deleted {len(passkeys) if passkeys else 0} passkeys")
        except Exception as e:
            logger.error(f"[ACCOUNT_RESET] Error deleting passkeys: {e}", exc_info=True)
            return False
        
        # 5. Clear cache for user
        try:
            await cache_service.delete_user_cache(user_id)
            await cache_service.delete_user_sessions(user_id)
            logger.info(f"[ACCOUNT_RESET] Cleared cache and sessions for user {user_id[:8]}...")
        except Exception as e:
            logger.error(f"[ACCOUNT_RESET] Error clearing cache: {e}", exc_info=True)
            return False
        
        logger.info(f"[ACCOUNT_RESET] Client data deletion complete for user {user_id[:8]}...")
        return True
        
    except Exception as e:
        logger.error(f"[ACCOUNT_RESET] Error deleting client data: {e}", exc_info=True)
        return False


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/cancel-reset/current", response_model=RecoveryCompleteResponse)
@limiter.limit("10/hour")
async def cancel_pending_reset_current_session(
    request: Request,
    user=Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """An existing authenticated device can cancel destruction before due time."""
    pending = await _pending_reset(directus_service, user.id)
    if not pending:
        return RecoveryCompleteResponse(success=True, state="cancelled", message="No pending reset remains.")
    due_at = parse_recovery_due_at(pending["due_at"])
    if pending["state"] != "pending" or datetime.now(timezone.utc) >= due_at:
        return RecoveryCompleteResponse(success=False, message="The cancellation period has ended.", error_code="CANCELLATION_CLOSED")
    updated = await cancel_pending_reset_if_current(directus_service, pending)
    if not updated:
        return RecoveryCompleteResponse(success=False, message="Could not cancel reset. Please try again.", error_code="CANCEL_FAILED")
    await cache_service.delete(f"recovery_cancel_token:{user.id}")
    return RecoveryCompleteResponse(success=True, state="cancelled", message="Account reset cancelled.")


@router.post("/cancel-reset", response_model=RecoveryCompleteResponse)
@limiter.limit("5/hour")
async def cancel_pending_reset(
    request: Request,
    cancel_request: RecoveryCancelRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """Cancel pending destruction using a fresh email verification token."""
    email = cancel_request.email.lower().strip()
    token_key = f"recovery_verify_token:{email}"
    stored_token = await cache_service.get(token_key)
    exists, user, _ = await directus_service.get_user_by_hashed_email(_hash_email(email))
    if not exists or not user:
        return RecoveryCompleteResponse(success=False, message="Account not found.", error_code="ACCOUNT_NOT_FOUND")
    cancel_hash = await cache_service.get(f"recovery_cancel_token:{user['id']}")
    presented_hash = hashlib.sha256(cancel_request.verification_token.encode()).hexdigest()
    valid_email_proof = bool(stored_token) and secrets.compare_digest(str(stored_token), cancel_request.verification_token)
    valid_cancel_proof = bool(cancel_hash) and secrets.compare_digest(str(cancel_hash), presented_hash)
    if not valid_email_proof and not valid_cancel_proof:
        return RecoveryCompleteResponse(success=False, message="Verification expired or invalid.", error_code="INVALID_TOKEN")
    pending = await _pending_reset(directus_service, user["id"])
    if not pending:
        return RecoveryCompleteResponse(success=True, state="cancelled", message="No pending reset remains.")
    due_at = parse_recovery_due_at(pending["due_at"])
    if pending["state"] != "pending" or datetime.now(timezone.utc) >= due_at:
        return RecoveryCompleteResponse(success=False, message="The cancellation period has ended.", error_code="CANCELLATION_CLOSED")
    updated = await cancel_pending_reset_if_current(directus_service, pending)
    if not updated:
        return RecoveryCompleteResponse(success=False, message="Could not cancel reset. Please try again.", error_code="CANCEL_FAILED")
    await cache_service.delete(token_key)
    await cache_service.delete(f"recovery_cancel_token:{user['id']}")
    return RecoveryCompleteResponse(success=True, state="cancelled", message="Account reset cancelled. Your existing login methods and encrypted history remain available.")

@router.post("/request-code", response_model=RecoveryRequestResponse)
@limiter.limit("3/hour")
async def request_recovery_code(
    request: Request,
    recovery_request: RecoveryRequestRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Request account reset by email.
    Sends a verification code to the email if the account exists.
    
    Rate limited: 3 requests per email per hour.
    
    Security: Always returns success to prevent email enumeration.
    """
    logger.info("Processing /recovery/request")
    
    try:
        email = recovery_request.email.lower().strip()
        hashed_email = _hash_email(email)
        
        # Check if user exists
        exists, user_data, error_msg = await directus_service.get_user_by_hashed_email(hashed_email)
        
        # Log the attempt (for audit trail)
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        
        if not exists or not user_data:
            # User doesn't exist, but we return success to prevent enumeration
            logger.info("Recovery requested for non-existent account")
            compliance_service.log_auth_event(
                event_type="recovery_requested",
                user_id=None,
                ip_address=client_ip,
                status="account_not_found",
                details={"hashed_email": hashed_email[:16] + "..."}
            )
            # Return success to prevent email enumeration
            return RecoveryRequestResponse(
                success=True,
                message="If an account exists with this email, a verification code will be sent."
            )
        
        user_id = user_data.get("id")
        
        # Log the recovery request
        compliance_service.log_auth_event(
            event_type="recovery_requested",
            user_id=user_id,
            ip_address=client_ip,
            status="code_sent"
        )
        
        # Send recovery email via Celery task
        # Reuses the confirm-email template with a different cache key
        try:
            celery_app.send_task(
                name='app.tasks.email_tasks.recovery_email_task.send_account_recovery_email',
                kwargs={
                    'email': email,
                    'language': recovery_request.language,
                    'darkmode': recovery_request.darkmode
                },
                queue='email'
            )
            logger.info(f"Recovery email task dispatched for user {user_id[:8]}...")
        except Exception as e:
            logger.error(f"Failed to dispatch recovery email task: {e}", exc_info=True)
            # Don't reveal the error to the user
        
        return RecoveryRequestResponse(
            success=True,
            message="If an account exists with this email, a verification code will be sent."
        )
        
    except Exception as e:
        logger.error(f"Error in recovery request: {e}", exc_info=True)
        return RecoveryRequestResponse(
            success=False,
            message="An error occurred. Please try again later.",
            error_code="SERVER_ERROR"
        )


@router.post("/verify-code", response_model=RecoveryVerifyResponse)
@limiter.limit("5/hour")
async def verify_recovery_code(
    request: Request,
    verify_request: RecoveryVerifyRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Verify the recovery code before proceeding to account reset.
    
    Returns a one-time verification token that must be used within 10 minutes
    to complete the account reset. This allows the frontend to show the login
    method selection UI without storing the verification code client-side.
    
    Rate limited: 5 attempts per hour (to prevent brute force).
    """
    logger.info("Processing /recovery/verify-code")
    
    try:
        email = verify_request.email.lower().strip()
        
        # Verify the code from cache
        cache_key = f"account_recovery:{email}"
        stored_code = await cache_service.get(cache_key)
        
        if not stored_code:
            logger.warning("Recovery code verification attempted with no code on record")
            return RecoveryVerifyResponse(
                success=False,
                message="No reset code found or code expired. Please request a new code.",
                error_code="CODE_EXPIRED"
            )
        
        if str(stored_code) != str(verify_request.code):
            logger.warning("Invalid recovery verification code")
            # Log failed attempt
            client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
            compliance_service.log_auth_event(
                event_type="recovery_verify_failed",
                user_id=None,
                ip_address=client_ip,
                status="invalid_code"
            )
            return RecoveryVerifyResponse(
                success=False,
                message="Invalid verification code. Please try again.",
                error_code="INVALID_CODE"
            )
        
        # Code is valid! Generate a one-time verification token
        verification_token = secrets.token_urlsafe(32)
        
        # Store token in cache (10 minutes expiry)
        token_cache_key = f"recovery_verify_token:{email}"
        await cache_service.set(token_cache_key, verification_token, ttl=600)  # 10 minutes
        
        # Delete the verification code (one-time use)
        await cache_service.delete(cache_key)
        
        # Look up user to check if they have 2FA configured
        # This info is needed by frontend to determine if 2FA setup is required
        # CRITICAL: Check encrypted_tfa_secret existence - this is the actual 2FA data
        # Note: There is NO tfa_enabled field in Directus schema - it only exists in cache
        # The presence of encrypted_tfa_secret is the source of truth for 2FA status
        hashed_email = _hash_email(email)
        has_2fa = False
        pending_until = None
        try:
            exists, user_data, _ = await directus_service.get_user_by_hashed_email(hashed_email)
            if exists and user_data:
                # User has 2FA if they have an encrypted secret stored in the database
                # This is consistent with auth_login.py which also checks encrypted_tfa_secret
                has_2fa = bool(user_data.get("encrypted_tfa_secret"))
                pending = await _pending_reset(directus_service, user_data["id"])
                if pending and pending["state"] == "pending":
                    pending_until = pending["due_at"]
                logger.info(f"User 2FA status: has_2fa={has_2fa} (encrypted_tfa_secret exists: {has_2fa})")
        except Exception as e:
            logger.warning(f"Could not check user 2FA status: {e}")
            # Default to requiring 2FA setup if we can't determine status
            has_2fa = False
        
        logger.info(f"Recovery code verified successfully for {email[:2]}***, has_2fa={has_2fa}")
        
        return RecoveryVerifyResponse(
            success=True,
            message="Verification successful. Please set up your new login method.",
            verification_token=verification_token,
            has_2fa=has_2fa,
            pending_until=pending_until,
        )
        
    except Exception as e:
        logger.error(f"Error in recovery verify: {e}", exc_info=True)
        return RecoveryVerifyResponse(
            success=False,
            message="An error occurred. Please try again.",
            error_code="SERVER_ERROR"
        )


@router.post("/setup-2fa", response_model=Recovery2FASetupResponse)
@limiter.limit("10/hour")
async def setup_2fa_for_recovery(
    request: Request,
    setup_request: Recovery2FASetupRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Generate 2FA setup data during account recovery.
    
    This endpoint is for users who don't have 2FA configured and are using
    password as their new login method. 2FA is mandatory for password-based accounts.
    
    Uses the verification token from verify-code endpoint for authorization.
    
    Returns the 2FA secret and otpauth URL for QR code generation.
    The secret is NOT stored yet - it will be encrypted and stored during the
    reset-account step after the user verifies their code.
    
    Rate limited: 10 per hour.
    """
    logger.info("Processing /recovery/setup-2fa")
    
    try:
        email = setup_request.email.lower().strip()
        
        # Verify the verification token from cache
        token_cache_key = f"recovery_verify_token:{email}"
        stored_token = await cache_service.get(token_cache_key)
        
        if not stored_token:
            logger.warning("2FA setup attempted with no verification token on record")
            return Recovery2FASetupResponse(
                success=False,
                message="Verification expired. Please verify your code again.",
                error_code="TOKEN_EXPIRED"
            )
        
        if str(stored_token) != str(setup_request.verification_token):
            logger.warning("Invalid verification token for 2FA setup")
            return Recovery2FASetupResponse(
                success=False,
                message="Invalid verification. Please start the recovery process again.",
                error_code="INVALID_TOKEN"
            )
        
        # Get user's email for the 2FA display name
        hashed_email = _hash_email(email)
        username = "User"
        try:
            exists, user_data, _ = await directus_service.get_user_by_hashed_email(hashed_email)
            if exists and user_data and user_data.get("encrypted_username"):
                # We can't decrypt username without vault key here, so just use email prefix
                username = email.split("@")[0] if "@" in email else "User"
        except Exception as e:
            logger.warning(f"Could not get username for 2FA setup: {e}")
        
        # Generate 2FA secret and otpauth URL
        secret, otpauth_url, _ = generate_2fa_secret(app_name="OpenMates", username=username)
        
        logger.info(f"Generated 2FA setup data for recovery user {email[:2]}***")
        
        return Recovery2FASetupResponse(
            success=True,
            message="2FA setup data generated. Please scan the QR code and enter the verification code.",
            secret=secret,
            otpauth_url=otpauth_url
        )
        
    except Exception as e:
        logger.error(f"Error in recovery 2FA setup: {e}", exc_info=True)
        return Recovery2FASetupResponse(
            success=False,
            message="An error occurred. Please try again.",
            error_code="SERVER_ERROR"
        )


@router.post("/reset-account", response_model=RecoveryCompleteResponse)
@limiter.limit("10/day")
async def reset_account(
    request: Request,
    reset_request: RecoveryFullResetRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Complete account reset with verification token.
    
    This is a LAST RESORT for users who lost all login methods AND their recovery key.
    
    WARNING: This permanently deletes all client-encrypted data:
    - All chats and messages
    - All app memories
    - All embeds
    
    Server-encrypted data (credits, username, subscription) is preserved.
    
    Rate limited: 10 per account per 24 hours (allows for testing/retry scenarios
    while still preventing abuse - the email verification code provides the main
    security layer).
    
    Requires verification_token from verify-code endpoint.
    """
    logger.info("Processing /recovery/reset-account")
    claimed_pending = None
    try:
        # 1. Verify user acknowledged data loss
        if not reset_request.acknowledge_data_loss:
            return RecoveryCompleteResponse(
                success=False,
                message="You must acknowledge that all chats, settings, and memories will be permanently deleted.",
                error_code="DATA_LOSS_NOT_ACKNOWLEDGED"
            )
        is_v2_password = reset_request.new_login_method == "password"
        if is_v2_password:
            try:
                decode_key(reset_request.password_auth_key.get_secret_value())
            except (AttributeError, ValueError):
                return RecoveryCompleteResponse(success=False, message="Invalid password recovery credentials.", error_code="INVALID_CREDENTIALS")
            if (reset_request.credential_version != 2 or reset_request.lookup_hash
                    or reset_request.salt != reset_request.user_email_salt):
                return RecoveryCompleteResponse(success=False, message="Password recovery requires v2 credentials.", error_code="CREDENTIAL_VERSION_REQUIRED")
        elif not reset_request.lookup_hash:
            return RecoveryCompleteResponse(success=False, message="Passkey recovery credentials are incomplete.", error_code="INVALID_CREDENTIALS")
        
        email = reset_request.email.lower().strip()
        hashed_email = _hash_email(email)
        if not secrets.compare_digest(reset_request.hashed_email, hashed_email):
            return RecoveryCompleteResponse(success=False, message="Email identity does not match the verified request.", error_code="EMAIL_MISMATCH")
        
        # 2. Verify the verification token from cache
        token_cache_key = f"recovery_verify_token:{email}"
        stored_token = await cache_service.get(token_cache_key)
        
        if not stored_token:
            logger.warning("Recovery attempted with no verification token on record")
            return RecoveryCompleteResponse(
                success=False,
                message="Verification expired. Please verify your code again.",
                error_code="TOKEN_EXPIRED"
            )
        
        if str(stored_token) != str(reset_request.verification_token):
            logger.warning("Invalid recovery verification token")
            return RecoveryCompleteResponse(
                success=False,
                message="Invalid verification. Please start the recovery process again.",
                error_code="INVALID_TOKEN"
            )
        
        # 3. Get user data
        exists, user_data, _ = await directus_service.get_user_by_hashed_email(hashed_email)
        
        if not exists or not user_data:
            logger.error("User not found after code verification")
            return RecoveryCompleteResponse(
                success=False,
                message="Account not found. Please contact support.",
                error_code="ACCOUNT_NOT_FOUND"
            )
        
        user_id = user_data.get("id")
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        vault_key_id = user_data.get("vault_key_id")

        # An email code may only open a cancellable recovery window. Existing
        # credentials and encrypted content remain usable throughout the delay.
        pending = await _pending_reset(directus_service, user_id)
        now = datetime.now(timezone.utc)
        if not pending:
            due_at = now + RECOVERY_DELAY
            created, _ = await directus_service.create_item(RECOVERY_COLLECTION, {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "hashed_email": hashed_email,
                "state": "pending",
                "version": 0,
                "requested_at": now.isoformat(),
                "due_at": due_at.isoformat(),
            }, admin_required=True)
            if not created:
                return RecoveryCompleteResponse(success=False, message="Could not schedule recovery. Please try again.", error_code="SCHEDULE_FAILED")
            cancellation_token = secrets.token_urlsafe(32)
            cancellation_saved = await cache_service.set(
                f"recovery_cancel_token:{user_id}",
                hashlib.sha256(cancellation_token.encode()).hexdigest(),
                ttl=int(RECOVERY_DELAY.total_seconds()),
            )
            if not cancellation_saved:
                await directus_service.update_item(RECOVERY_COLLECTION, created["id"], {"state": "cancelled"}, admin_required=True)
                return RecoveryCompleteResponse(success=False, message="Could not prepare cancellation. Please try again.", error_code="CANCEL_SETUP_FAILED")
            try:
                celery_app.send_task(
                    name="app.tasks.email_tasks.recovery_email_task.send_recovery_pending_email",
                    kwargs={"email": email, "language": "en"}, queue="email",
                )
            except Exception:
                await directus_service.update_item(
                    RECOVERY_COLLECTION, created["id"],
                    {"state": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()},
                    admin_required=True,
                )
                return RecoveryCompleteResponse(success=False, message="Could not send recovery notice. Please try again.", error_code="NOTICE_FAILED")
            await cache_service.delete(token_cache_key)
            return RecoveryCompleteResponse(
                success=True,
                state="pending",
                pending_until=due_at.isoformat(),
                cancellation_token=cancellation_token,
                message="Account reset is scheduled for 24 hours from now. You can cancel during this period. Return with a new email code after the delay to finish reset.",
            )
        due_at = parse_recovery_due_at(pending["due_at"])
        if now < due_at:
            return RecoveryCompleteResponse(
                success=True, state="pending", pending_until=due_at.isoformat(),
                message="Account reset is pending. You can cancel until the 24-hour delay ends.",
            )
        if pending["state"] != "pending":
            return RecoveryCompleteResponse(success=False, message="Recovery is already processing. Please try again later.", error_code="PROCESSING")
        verified_passkey = None
        if reset_request.new_login_method == "passkey":
            credential = reset_request.passkey_credential or {}
            if not credential.get("prf_enabled") or not credential.get("credential_id"):
                return RecoveryCompleteResponse(success=False, message="Verified PRF passkey registration is required.", error_code="PASSKEY_REQUIRED")
            from backend.core.api.app.routes.auth_routes.auth_passkey import verify_registration_attestation
            try:
                public_cose, public_jwk, aaguid = await verify_registration_attestation(
                    request, cache_service,
                    credential_id=credential["credential_id"],
                    attestation_response=credential.get("attestation_response") or {},
                    client_data_json=credential.get("client_data_json") or "",
                    hashed_email=hashed_email,
                    challenge_user_id=None,
                )
            except ValueError:
                return RecoveryCompleteResponse(success=False, message="Passkey registration could not be verified.", error_code="PASSKEY_VERIFICATION_FAILED")
            verified_passkey = (credential, public_cose, public_jwk, aaguid)
        
        # 4. Get username for response (before we delete data)
        username = None
        if vault_key_id and user_data.get("encrypted_username"):
            try:
                username = await encryption_service.decrypt_with_user_key(
                    user_data["encrypted_username"], vault_key_id
                )
            except Exception as e:
                logger.warning(f"Could not decrypt username: {e}")
        
        # 4.5. Optional 2FA enrollment during password recovery.
        # CRITICAL: Check encrypted_tfa_secret existence - this is the actual 2FA data
        # Note: There is NO tfa_enabled field in Directus schema - it only exists in cache
        # The presence of encrypted_tfa_secret is the source of truth for 2FA status
        # (consistent with verify-code endpoint above)
        has_existing_2fa = bool(user_data.get("encrypted_tfa_secret"))
        encrypted_tfa_secret = None
        encrypted_tfa_app_name = None
        
        if is_v2_password and not has_existing_2fa and (
            reset_request.tfa_secret or reset_request.tfa_verification_code
        ):
            if not reset_request.tfa_secret or not reset_request.tfa_verification_code:
                logger.warning("Password recovery attempted without 2FA setup")
                return RecoveryCompleteResponse(
                    success=False,
                    message="Complete both fields to enroll an authenticator app.",
                    error_code="2FA_SETUP_INCOMPLETE"
                )
            
            # Verify the 2FA code
            try:
                totp = pyotp.TOTP(reset_request.tfa_secret)
                if not totp.verify(reset_request.tfa_verification_code, valid_window=1):
                    logger.warning("Invalid 2FA verification code during recovery")
                    return RecoveryCompleteResponse(
                        success=False,
                        message="Invalid verification code. Please check your 2FA app and try again.",
                        error_code="INVALID_2FA_CODE"
                    )
            except Exception as e:
                logger.error(f"Error verifying 2FA code: {e}")
                return RecoveryCompleteResponse(
                    success=False,
                    message="Failed to verify 2FA code. Please try again.",
                    error_code="2FA_VERIFICATION_FAILED"
                )
            
            # Encrypt the 2FA secret for storage using vault
            # encrypt_with_user_key returns (ciphertext, key_version) tuple
            try:
                encrypted_tfa_secret, _ = await encryption_service.encrypt_with_user_key(
                    reset_request.tfa_secret, vault_key_id
                )
                if reset_request.tfa_app_name:
                    encrypted_tfa_app_name, _ = await encryption_service.encrypt_with_user_key(
                        reset_request.tfa_app_name, vault_key_id
                    )
                logger.info(f"Encrypted new 2FA secret for user {user_id[:8]}... (has vault: prefix: {encrypted_tfa_secret.startswith('vault:')})")
            except Exception as e:
                logger.error(f"Failed to encrypt 2FA secret: {e}")
                return RecoveryCompleteResponse(
                    success=False,
                    message="Failed to secure 2FA data. Please try again.",
                    error_code="ENCRYPTION_FAILED"
                )

        sealed_auth_key = None
        wrapper_method = None
        if is_v2_password:
            try:
                sealed_auth_key = await seal_auth_key(
                    encryption_service,
                    password_auth_key=reset_request.password_auth_key.get_secret_value(),
                    vault_key_id=vault_key_id,
                )
            except Exception:
                return RecoveryCompleteResponse(success=False, message="Could not secure the new password. Please try again.", error_code="AUTH_KEY_SEAL_FAILED")
            wrapper_method = f"password_v2_{secrets.token_hex(16)}"

        # The new email proof is one-use and can finalize only after the delay
        # and all non-destructive credential validation has passed.
        await cache_service.delete(token_cache_key)
        claimed = await directus_service.update_item_if_version(
            RECOVERY_COLLECTION, pending["id"],
            {"state": "processing", "version": int(pending["version"]) + 1},
            int(pending["version"]), extra_filters={"state": "pending"}, admin_required=True,
        )
        if not claimed:
            return RecoveryCompleteResponse(success=False, message="Could not start recovery. Please try again.", error_code="CLAIM_FAILED")
        claimed_pending = pending

        # A destructive reset invalidates every online credential before data
        # can change; failures must stop the operation rather than leave access.
        await revoke_all_user_sessions(directus_service, cache_service, user_id)
        if not await directus_service.revoke_user_api_keys(user_id):
            return await _retryable_reset_failure(directus_service, pending, "Could not revoke API keys. Please try again later.", "REVOCATION_INCOMPLETE")
        
        # 5. Delete all client-encrypted data
        logger.info(f"[ACCOUNT_RESET] Starting full reset for user {user_id[:8]}...")
        
        delete_success = await _delete_user_client_data(
            user_id=user_id,
            user_id_hash=user_id_hash,
            directus_service=directus_service,
            cache_service=cache_service
        )
        
        if not delete_success:
            logger.error(f"Failed to delete client data for user {user_id[:8]}...")
            return await _retryable_reset_failure(directus_service, pending, "Account cleanup is incomplete. Please try again later.", "CLEANUP_INCOMPLETE")
        
        # Snapshot old wrappers before creating the replacement. They are removed
        # only after both replacement credentials and the user record are saved.
        old_keys = await directus_service.get_items(
            "encryption_keys", params={"filter": {"hashed_user_id": {"_eq": user_id_hash}}},
            no_cache=True, raise_on_error=True,
        )

        if verified_passkey:
            credential, public_cose, public_jwk, aaguid = verified_passkey
            registered = await directus_service.create_passkey(
                hashed_user_id=user_id_hash,
                user_id=user_id,
                credential_id=credential["credential_id"],
                public_key_cose_b64=public_cose,
                public_key_jwk=public_jwk,
                aaguid=str(aaguid) if aaguid else None,
                encrypted_device_name=credential.get("encrypted_device_name"),
            )
            if not registered:
                return await _retryable_reset_failure(directus_service, pending, "Could not save the verified passkey. Please try again.", "PASSKEY_STORAGE_FAILED")

        # 7. Create new encryption key record
        try:
            key_created = await directus_service.create_encryption_key(
                hashed_user_id=user_id_hash,
                login_method=(wrapper_method if is_v2_password else
                              f"passkey_{hashlib.sha256(verified_passkey[0]['credential_id'].encode()).hexdigest()}"),
                encrypted_key=reset_request.encrypted_master_key,
                salt=reset_request.salt,
                key_iv=reset_request.key_iv
            )
            if not key_created:
                raise RuntimeError("Encryption key creation returned unsuccessful status")
            logger.info(f"Created new encryption key for user {user_id[:8]}...")
        except Exception as e:
            logger.error(f"Error creating encryption key: {e}", exc_info=True)
            return await _retryable_reset_failure(directus_service, pending, "Failed to set up new credentials. Please try again.", "KEY_CREATION_FAILED")

        # 6. Update user with new credentials and clear client-encrypted fields
        update_data = {
            # New authentication data
            "hashed_email": reset_request.hashed_email,
            "encrypted_email_address": reset_request.encrypted_email,
            "encrypted_email_with_master_key": reset_request.encrypted_email_with_master_key,
            "user_email_salt": reset_request.user_email_salt,
            "lookup_hashes": [] if is_v2_password else [reset_request.lookup_hash],
            "credential_lookup_hashes": {
                ("password" if is_v2_password else
                 f"passkey_{hashlib.sha256(verified_passkey[0]['credential_id'].encode()).hexdigest()}"):
                ({"version": 2, "kdf": KDF_ID, "sealed_auth_key": sealed_auth_key,
                  "wrapper_method": wrapper_method, "legacy_password_retained": False}
                 if is_v2_password else reset_request.lookup_hash)
            },
            
            # Clear client-encrypted fields that are now inaccessible
            "encrypted_settings": None,
            "encrypted_hidden_demo_chats": None,
            "encrypted_top_recommended_apps": None,
            
            # Reset recovery key confirmation (user will need to set up new one)
            "consent_recovery_key_stored_timestamp": None,
        }
        
        # Add 2FA data if it was set up during recovery
        if encrypted_tfa_secret:
            update_data["encrypted_tfa_secret"] = encrypted_tfa_secret
            update_data["tfa_enabled"] = True
            logger.info(f"Including new 2FA secret in user update for {user_id[:8]}...")
        if encrypted_tfa_app_name:
            update_data["encrypted_tfa_app_name"] = encrypted_tfa_app_name
        
        update_success = await directus_service.update_user(user_id, update_data)
        if not update_success:
            logger.error(f"Failed to update user during recovery: {user_id[:8]}...")
            if is_v2_password and wrapper_method:
                await directus_service.delete_encryption_key(user_id_hash, wrapper_method)
            return await _retryable_reset_failure(directus_service, pending, "Failed to update account. Please try again.", "UPDATE_FAILED")

        for old_key in old_keys or []:
            old_key_id = old_key.get("id")
            if old_key_id and not await directus_service.delete_item("encryption_keys", old_key_id, admin_required=True):
                return await _retryable_reset_failure(directus_service, pending, "Old credentials could not be fully removed. Please try again.", "OLD_KEY_CLEANUP_FAILED")

        completed = await directus_service.update_item(RECOVERY_COLLECTION, pending["id"], {
            "state": "complete", "completed_at": datetime.now(timezone.utc).isoformat()
        }, admin_required=True)
        if not completed:
            return await _retryable_reset_failure(directus_service, pending, "Recovery confirmation is pending. Please try again.", "COMPLETION_UNCONFIRMED")
        claimed_pending = None
        
        # 8. Log the recovery completion
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        compliance_service.log_auth_event(
            event_type="recovery_full_reset",
            user_id=user_id,
            ip_address=client_ip,
            status="success",
            details={"new_login_method": reset_request.new_login_method}
        )
        
        logger.info(f"[ACCOUNT_RESET] Full reset completed for user {user_id[:8]}...")
        
        return RecoveryCompleteResponse(
            success=True,
            message="Account reset successfully. Please log in with your new credentials.",
            user_id=user_id,
            username=username
        )
        
    except Exception as e:
        logger.error(f"Error in full reset recovery: {e}", exc_info=True)
        if claimed_pending:
            return await _retryable_reset_failure(
                directus_service, claimed_pending,
                "An error occurred during account reset. Please try again.", "SERVER_ERROR",
            )
        return RecoveryCompleteResponse(
            success=False,
            message="An error occurred during account reset. Please try again.",
            error_code="SERVER_ERROR"
        )
