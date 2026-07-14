import base64
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.core.api.app.schemas.auth import (
    DevSignupCleanupRequest,
    DevSignupCleanupResponse,
    InviteCodeRequest,
    InviteCodeResponse,
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.invite_code import validate_invite_code
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_metrics_service,
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin

router = APIRouter()
logger = logging.getLogger(__name__)


def _is_production_environment() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development").strip().lower() in {"production", "prod"}


def _configured_test_account_hashes() -> set[str]:
    hashes: set[str] = set()
    for key, value in os.environ.items():
        if not key.startswith("OPENMATES_TEST_ACCOUNT") or not key.endswith("EMAIL"):
            continue
        if not value or "@" not in value:
            continue
        digest = hashlib.sha256(value.lower().strip().encode()).digest()
        hashes.add(base64.b64encode(digest).decode())
    return hashes


def _verify_dev_cleanup_secret(request: Request) -> None:
    expected_key = os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY", "")
    if not expected_key:
        logger.error("Dev signup cleanup called but OPENMATES_TEST_ACCOUNT_API_KEY is not configured.")
        raise HTTPException(status_code=500, detail="Dev signup cleanup is not configured")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing cleanup API key")

    provided_key = auth_header[7:]
    if not hmac.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=403, detail="Invalid cleanup API key")


@router.post("/check_invite_token_valid", response_model=InviteCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def check_invite_token_valid(
    request: Request,
    invite_request: InviteCodeRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """
    Check if the provided invite code is valid.
    If valid, store it in a secure HTTP-only cookie.
    """
    try:
        is_valid, message, code_data = await validate_invite_code(invite_request.invite_code, directus_service, cache_service)
        metrics_service.track_invite_code_check(is_valid)
        
        if is_valid:
            # Kept for response compatibility. Invite codes no longer grant
            # admin privileges; use `openmates server make-admin <email>`.
            is_admin = False
            gifted_credits = code_data.get('gifted_credits') if code_data else None
            
            return InviteCodeResponse(
                valid=True, 
                message=message,
                is_admin=is_admin,
                gifted_credits=gifted_credits
            )
        else:
            return InviteCodeResponse(valid=False, message=message)
    
    except Exception as e:
        metrics_service.track_invite_code_check(False)
        logger.error(f"Error validating invite code: {str(e)}", exc_info=True)
        return InviteCodeResponse(valid=False, message="An error occurred checking the invite code")


@router.post(
    "/cleanup_failed_signup",
    response_model=DevSignupCleanupResponse,
    include_in_schema=False,
)
@limiter.limit("20/minute")
async def cleanup_failed_signup(
    request: Request,
    cleanup_request: DevSignupCleanupRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> DevSignupCleanupResponse:
    """Queue deletion for one disposable signup account after a failed dev E2E run."""
    if _is_production_environment():
        raise HTTPException(status_code=404, detail="Not found")
    _verify_dev_cleanup_secret(request)

    hashed_email = cleanup_request.hashed_email.strip()
    if not hashed_email:
        raise HTTPException(status_code=400, detail="hashed_email is required")
    if hashed_email in _configured_test_account_hashes():
        raise HTTPException(status_code=403, detail="Refusing to delete a configured test account")

    exists, target_user, message = await directus_service.get_user_by_hashed_email(hashed_email)
    if not exists or not target_user:
        return DevSignupCleanupResponse(
            success=True,
            deleted=False,
            queued=False,
            message="No matching disposable signup account found",
        )

    target_user_id = target_user.get("id")
    if not target_user_id:
        logger.error("Dev signup cleanup matched a user without an id: %s", message)
        raise HTTPException(status_code=500, detail="Matched user record is missing an id")
    if target_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Refusing to delete an admin user")

    from backend.core.api.app.tasks.celery_config import app as celery_app

    test_file = (cleanup_request.test_file or "unknown signup spec")[:120]
    reason = (cleanup_request.reason or "Failed dev signup E2E cleanup")[:200]
    task_result = celery_app.send_task(
        name="delete_user_account",
        kwargs={
            "user_id": target_user_id,
            "deletion_type": "dev_failed_signup_e2e_cleanup",
            "reason": f"{reason} ({test_file})",
            "ip_address": None,
            "device_fingerprint": None,
            "refund_invoices": False,
        },
        queue="user_init",
    )
    await cache_service.delete("require_invite_code")
    logger.info(
        "Queued dev failed-signup cleanup for user %s from %s",
        target_user_id[:8],
        test_file,
    )
    return DevSignupCleanupResponse(
        success=True,
        queued=True,
        deleted=True,
        message="Disposable signup account deletion queued",
        task_id=task_result.id,
    )
