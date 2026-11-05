"""Restrict an authenticated first-party request to its expected principal.

This optional assertion grants no authority. Normal session/API-key auth and
ACL/CSRF/origin checks remain mandatory; no cookie or token is read here.
"""
import hashlib
from uuid import UUID
from fastapi import HTTPException, Request, Response

EXPECTED_PRINCIPAL_HEADER = "X-OpenMates-Expected-Principal"
OWNER_CONSISTENCY_CAPABILITIES = ("expected-principal-v1", "ws-dual-principal-v1")


def require_expected_principal(request: Request | None, authenticated_principal: str) -> None:
    if request is None:
        return
    values = request.headers.getlist(EXPECTED_PRINCIPAL_HEADER)
    if not values:
        return
    valid = len(values) == 1 and len(values[0]) == 36
    if valid:
        try:
            valid = str(UUID(values[0])) == values[0] == authenticated_principal
        except (ValueError, TypeError, AttributeError):
            valid = False
    if not valid:
        # Never echo either authenticated or requested owner into an error/log.
        raise HTTPException(403, detail={"error": "session_principal_mismatch"})


async def require_expected_owner_before_refresh(request: Request | None, directus_service, refresh_token: str) -> None:
    """Check an opt-in assertion before Directus refresh rotation or cache writes.

    On a session-cache miss the owner is read from the durable session ledger
    without mutation. A supplied assertion whose owner cannot be read this way
    fails closed, so a mismatched request never rotates or caches a session.
    """
    if request is None or not request.headers.getlist(EXPECTED_PRINCIPAL_HEADER):
        return
    from backend.core.api.app.services.session_security_state import get_session_state
    row = await get_session_state(directus_service, hashlib.sha256(refresh_token.encode()).hexdigest())
    owner = row.get("user_id") if isinstance(row, dict) else None
    require_expected_principal(request, owner if isinstance(owner, str) else "")


def is_expected_principal_mismatch(error: HTTPException) -> bool:
    """Only the closed owner-consistency refusal is terminal for fallback."""
    return error.status_code == 403 and error.detail == {"error": "session_principal_mismatch"}


async def restrict_expected_cookie_principal(request: Request, response: Response) -> None:
    """Before independent logout handlers, opt-in assertions use normal auth.

    Absent assertion keeps existing cookie-clearing legacy behavior. Supplied
    assertion never grants authority or lets a mismatch clear another session.
    A cookie that no longer authenticates (401) names no account, so the
    logout handler still clears it; only the closed mismatch refusal blocks.
    """
    if not request.headers.getlist(EXPECTED_PRINCIPAL_HEADER):
        return
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
    try:
        user = await get_current_user(
            directus_service=request.app.state.directus_service,
            cache_service=request.app.state.cache_service,
            refresh_token=request.cookies.get("auth_refresh_token") or request.cookies.get("directus_refresh_token"),
            response=response,
            request=request,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return
        raise
    require_expected_principal(request, user.id)
