from fastapi import APIRouter, Depends, Request, Response
import logging
from app.schemas.auth import InviteCodeRequest, InviteCodeResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.limiter import limiter
from app.utils.invite_code import validate_invite_code
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service
from app.routes.auth_routes.auth_utils import verify_allowed_origin

router = APIRouter()
logger = logging.getLogger(__name__)

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
            # Set invite code in HTTP-only cookie
            response.set_cookie(
                key="signup_invite_code",
                value=invite_request.invite_code,
                httponly=True,
                secure=True,
                samesite="strict",
                max_age=3600  # 1 hour expiry
            )
            
            # Extract additional properties from code_data
            is_admin = code_data.get('is_admin', False) if code_data else False
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
