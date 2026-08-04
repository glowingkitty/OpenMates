"""
Authenticated account capability discovery for first-party clients.

This core auth route is available in every server edition and intentionally has
no payment or OpenMatesCloud dependency. All storage reads must succeed before a
capability response is returned so unknown state is never reported as false.
"""

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user,
    get_directus_service,
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter


logger = logging.getLogger(__name__)
router = APIRouter()


class AuthMethodsResponse(BaseModel):
    has_passkey: bool
    has_2fa: bool
    has_password: bool
    has_recovery_key: bool


@router.get("/methods", response_model=AuthMethodsResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def get_auth_methods(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> AuthMethodsResponse:
    auth_source = getattr(getattr(request, "state", None), "auth_source", None)
    if auth_source == "api_key":
        raise HTTPException(status_code=403, detail="First-party session required")

    try:
        passkeys = await directus_service.get_items(
            "user_passkeys",
            {
                "filter[user_id][_eq]": current_user.id,
                "fields": "id",
                "limit": 1,
            },
            raise_on_error=True,
        )
        hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        encryption_keys = await directus_service.get_items(
            "encryption_keys",
            {
                "filter[hashed_user_id][_eq]": hashed_user_id,
                "fields": "login_method",
            },
            raise_on_error=True,
        )
        users = await directus_service.get_items(
            "directus_users",
            {
                "filter[id][_eq]": current_user.id,
                "fields": "encrypted_tfa_secret",
                "limit": 1,
            },
            admin_required=True,
            raise_on_error=True,
        )
        if not users:
            raise RuntimeError("Authenticated user record was not found")
    except Exception as error:
        logger.error(
            "Authentication method storage lookup failed: %s",
            type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Authentication methods temporarily unavailable",
        ) from error

    login_methods = {item.get("login_method") for item in encryption_keys}
    user_fields = users[0] if users else {}
    return AuthMethodsResponse(
        has_passkey=bool(passkeys),
        has_2fa=bool(user_fields and user_fields.get("encrypted_tfa_secret")),
        has_password="password" in login_methods,
        has_recovery_key="recovery_key" in login_methods,
    )
