# backend/core/api/app/routes/wikipedia_proxy.py
#
# Privacy-preserving Wikipedia proxy endpoints.
#
# The frontend never contacts Wikipedia/Wikidata directly — all requests go
# through this proxy so the user's IP is never exposed to the Wikimedia Foundation.
#
# Access control (abuse protection for our outbound Wikipedia rate limit):
#   * Requests from the trusted web-app Origin → allowed (free, even unauthenticated)
#     — so unauth users viewing example chats can click wiki links.
#   * Session cookie (authenticated web-app user) → allowed (free).
#   * API key (external developers) → allowed, charges 1 credit per request.
#   * Anonymous requests without a trusted Origin AND without an API key → 401.
#
# Rate-limited at the FastAPI layer to cap even the trusted-origin path.
#
# The backend uses the existing wikipedia provider (backend/shared/providers/wikipedia)
# which sets a proper User-Agent per Wikimedia policy and handles retries.

import hashlib
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.core.api.app.routes.apps_api import charge_credits_via_internal_api
from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.wikipedia.wikipedia_api import (
    fetch_page_summary,
    fetch_wikidata_entity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/wikipedia", tags=["Wikipedia"])

# Credit cost per API-key request to the Wikipedia proxy
CREDITS_PER_REQUEST = 1

# Differentiated rate limits (per client IP):
#   - Authenticated (session cookie or API key): 60/min
#   - Anonymous origin-only (unauth web-app visitors): 15/min
# Protects outbound Wikipedia quota from unauth abuse while giving logged-in users
# reasonable headroom. SlowAPI evaluates the callable on every request.
def _wiki_rate_limit(request: Request) -> str:
    has_cookie = bool(request.cookies.get("auth_refresh_token"))
    auth_header = request.headers.get("Authorization", "")
    has_api_key = auth_header.startswith("Bearer ")
    return "60/minute" if (has_cookie or has_api_key) else "15/minute"


async def _authorize_request(request: Request) -> Dict[str, Any]:
    """
    Allow the request if ANY of the following is true, else raise 401:
      1. Origin header matches an allowed web-app origin (free, used for unauth
         users viewing example chats).
      2. Session cookie is valid (free).
      3. Bearer API key is valid (caller pays 1 credit).

    Returns a dict with auth context: { source: 'origin'|'session'|'api_key',
    user_id, api_key_hash, device_hash }. The credit-charging helper reads
    `api_key_hash` to decide whether to bill.
    """
    # 1. Trusted Origin check — fastest, covers unauthenticated web-app users
    origin = request.headers.get("origin") or request.headers.get("Origin")
    allowed_origins = getattr(request.app.state, "allowed_origins", []) or []
    if origin and origin in allowed_origins:
        return {"source": "origin", "user_id": None, "api_key_hash": None, "device_hash": None}

    # 2. Try session cookie OR 3. API key via the existing combined dependency
    try:
        from backend.core.api.app.routes.apps_api import get_session_or_api_key_info
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.services.directus import DirectusService

        # Manually resolve the dependency chain (we can't use Depends() inside a plain function).
        cache_service = CacheService()
        directus_service = DirectusService(cache_service=cache_service)
        refresh_token = request.cookies.get("auth_refresh_token")

        auth_info = await get_session_or_api_key_info(
            request=request,
            cache_service=cache_service,
            directus_service=directus_service,
            refresh_token=refresh_token,
        )
        return auth_info
    except HTTPException:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated: request must come from the web-app origin, include a valid session cookie, or a valid API key.",
        )


async def _charge_if_api_key(auth_info: Dict[str, Any], skill_id: str) -> None:
    """Charge 1 credit if the request used an API key (external developer).
    Web-app origin + session-cookie callers are free."""
    api_key_hash = auth_info.get("api_key_hash")
    user_id = auth_info.get("user_id")
    if not api_key_hash or not user_id:
        return
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    await charge_credits_via_internal_api(
        user_id=user_id,
        user_id_hash=user_id_hash,
        credits=CREDITS_PER_REQUEST,
        app_id="study",
        skill_id=skill_id,
        usage_details={"source": "wikipedia_proxy"},
        api_key_hash=api_key_hash,
        device_hash=auth_info.get("device_hash"),
    )


@router.get("/summary")
@limiter.limit(_wiki_rate_limit)
async def wikipedia_summary(
    request: Request,
    title: str = Query(..., min_length=1, max_length=300, description="Canonical Wikipedia article title"),
    language: str = Query("en", min_length=2, max_length=5, description="Wikipedia language code"),
) -> JSONResponse:
    """
    Proxy the Wikipedia REST API page summary endpoint.
    Returns title, description, extract, thumbnail, original image, Wikidata QID.

    Auth: trusted Origin OR session cookie (free) OR API key (1 credit per request).
    """
    if not all(c.isalnum() or c == "-" for c in language):
        raise HTTPException(status_code=400, detail="Invalid language code")

    auth_info = await _authorize_request(request)

    try:
        data = await fetch_page_summary(title=title, language=language)
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] summary fetch error for '{title}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia summary")

    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")

    await _charge_if_api_key(auth_info, skill_id="wikipedia_summary")
    return JSONResponse(content=data)


@router.get("/wikidata/{qid}")
@limiter.limit(_wiki_rate_limit)
async def wikidata_entity(request: Request, qid: str) -> JSONResponse:
    """
    Proxy a Wikidata entity lookup (structured claims, labels, descriptions).
    QID must match the Wikidata format (Q followed by digits).

    Auth: trusted Origin OR session cookie (free) OR API key (1 credit per request).
    """
    if not qid.startswith("Q") or not qid[1:].isdigit() or len(qid) > 20:
        raise HTTPException(status_code=400, detail="Invalid QID")

    auth_info = await _authorize_request(request)

    try:
        data = await fetch_wikidata_entity(qid=qid)
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] wikidata fetch error for '{qid}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikidata entity")

    if data is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    await _charge_if_api_key(auth_info, skill_id="wikidata_entity")
    return JSONResponse(content=data)
