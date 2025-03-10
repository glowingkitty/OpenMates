from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime

from app.schemas.auth import InviteCodeRequest, InviteCodeResponse
from app.services.directus import DirectusService

router = APIRouter(
    prefix="/v1/auth",
    tags=["Authentication"]
)

@router.post("/check_invite_token_valid", response_model=InviteCodeResponse)
async def check_invite_token_valid(
    request: InviteCodeRequest,
    directus_service: DirectusService = Depends(DirectusService)
):
    """
    Check if the provided invite code is valid.
    
    An invite code is valid if:
    1. It exists in the database
    2. It has remaining uses > 0
    3. Current time is after valid_from (if specified)
    4. Current time is before expire_date (if specified)
    """
    try:
        # Query the invite_codes collection in Directus
        code_data = await directus_service.get_invite_code(request.invite_code)
        
        if not code_data:
            return InviteCodeResponse(valid=False, message="Invalid invite code")
        
        # Check if code has remaining uses
        if code_data.get("remaining_uses", 0) <= 0:
            return InviteCodeResponse(valid=False, message="Invite code has been fully used")
            
        # Check if code is within valid date range
        now = datetime.now()
        
        # Check valid_from if it exists
        valid_from = code_data.get("valid_from")
        if valid_from and datetime.fromisoformat(valid_from.replace('Z', '+00:00')) > now:
            return InviteCodeResponse(valid=False, message="Invite code is not yet valid")
            
        # Check expire_date if it exists
        expire_date = code_data.get("expire_date")
        if expire_date and datetime.fromisoformat(expire_date.replace('Z', '+00:00')) < now:
            return InviteCodeResponse(valid=False, message="Invite code has expired")
            
        # Code is valid
        return InviteCodeResponse(
            valid=True,
            message="Invite code is valid", 
            is_admin=code_data.get("is_admin", False),
            gifted_credits=code_data.get("gifted_credits")
        )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error validating invite code: {str(e)}")
