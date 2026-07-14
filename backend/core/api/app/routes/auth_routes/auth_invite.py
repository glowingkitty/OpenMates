import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.core.api.app.models.user import User
from backend.core.api.app.schemas.auth import (
    E2ESignupInviteRestoreResponse,
    InviteCodeRequest,
    InviteCodeResponse,
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.invite_code import fingerprint_invite_code, validate_invite_code
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user_or_api_key,
    get_directus_service,
    get_cache_service,
    get_metrics_service,
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin

router = APIRouter()
logger = logging.getLogger(__name__)

E2E_INVITE_RESTORE_HEADER = "x-openmates-e2e-invite-restore"
E2E_INVITE_RESTORE_HEADER_VALUE = "restore"
E2E_INVITE_REMAINING_USES = 1000


def _is_production_environment() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development").strip().lower() in {"production", "prod"}

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
    "/e2e/restore_signup_invite_code",
    response_model=E2ESignupInviteRestoreResponse,
    include_in_schema=False,
)
@limiter.limit("10/minute")
async def restore_e2e_signup_invite_code(
    request: Request,
    invite_request: InviteCodeRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> E2ESignupInviteRestoreResponse:
    """Idempotently restore the CI signup invite code on dev/test servers."""
    if _is_production_environment():
        raise HTTPException(status_code=404, detail="Not found")

    if request.headers.get(E2E_INVITE_RESTORE_HEADER) != E2E_INVITE_RESTORE_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="E2E invite restore header required")

    invite_code = invite_request.invite_code.strip()
    if not invite_code:
        raise HTTPException(status_code=400, detail="Invite code is required")

    existing = await directus_service.get_invite_code(invite_code)
    payload = {
        "remaining_uses": E2E_INVITE_REMAINING_USES,
        "gifted_credits": 0,
        "is_admin": False,
    }

    if existing:
        updated = await directus_service.update_item(
            "invite_codes",
            existing["id"],
            payload,
            admin_required=True,
        )
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to refresh signup invite code")
        await cache_service.delete(f"invite_code:{invite_code}")
        logger.info(
            "E2E signup invite code refreshed by user %s: %s",
            current_user.id,
            fingerprint_invite_code(invite_code),
        )
        return E2ESignupInviteRestoreResponse(
            success=True,
            created=False,
            message="Signup invite code refreshed",
        )

    success, _created_item = await directus_service.create_item(
        "invite_codes",
        {"code": invite_code, **payload},
        admin_required=True,
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restore signup invite code")

    await cache_service.delete(f"invite_code:{invite_code}")
    logger.info(
        "E2E signup invite code restored by user %s: %s",
        current_user.id,
        fingerprint_invite_code(invite_code),
    )
    return E2ESignupInviteRestoreResponse(
        success=True,
        created=True,
        message="Signup invite code restored",
    )
