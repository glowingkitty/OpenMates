from fastapi import APIRouter, HTTPException, Depends, status, Request, Header
import logging

from app.schemas.auth import InviteCodeRequest, InviteCodeResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.limiter import limiter
from app.utils.invite_code import validate_invite_code

router = APIRouter(
    prefix="/v1/auth",
    tags=["Authentication"]
)

logger = logging.getLogger(__name__)

def get_directus_service():
    from main import directus_service
    return directus_service

def get_cache_service():
    from main import cache_service
    return cache_service

def get_metrics_service():
    from main import metrics_service
    return metrics_service

async def verify_allowed_origin(request: Request):
    """
    Security dependency to verify the request originates from an allowed origin.
    This prevents direct API access to auth endpoints that should only be used by the frontend.
    """
    origin = request.headers.get("origin")
    allowed_origins = request.app.state.allowed_origins
    
    if not origin or origin not in allowed_origins:
        logger.warning(f"Unauthorized origin access to auth endpoint: {request.url.path}, Origin: {origin}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Authentication endpoints can only be accessed from authorized applications"
        )
    
    return True

@router.post("/check_invite_token_valid", response_model=InviteCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def check_invite_token_valid(
    request: Request,
    invite_request: InviteCodeRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """
    Check if the provided invite code is valid.
    """
    try:
        is_valid, message = await validate_invite_code(invite_request.invite_code, directus_service, cache_service)
        metrics_service.track_invite_code_check(is_valid)
        
        if is_valid:
            return InviteCodeResponse(valid=True, message=message)
        else:
            return InviteCodeResponse(valid=False, message=message)
    
    except Exception as e:
        metrics_service.track_invite_code_check(False)
        logger.error(f"Error validating invite code: {str(e)}", exc_info=True)
        return InviteCodeResponse(valid=False, message="An error occurred checking the invite code")