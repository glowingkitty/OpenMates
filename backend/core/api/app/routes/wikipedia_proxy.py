# backend/core/api/app/routes/wikipedia_proxy.py
#
# Privacy-preserving Wikipedia proxy endpoints.
#
# The frontend never contacts Wikipedia/Wikidata directly — all requests go
# through this proxy so the user's IP is never exposed to the Wikimedia Foundation.
#
# Authentication:
#   * Session cookie (web app) — free (already rate-limited 60/min)
#   * API key (external developers) — charges 1 credit per request
#   * Anonymous access is BLOCKED (prevents abuse of our outbound rate limit to Wikipedia)
#
# The backend uses the existing wikipedia provider (backend/shared/providers/wikipedia)
# which sets a proper User-Agent per Wikimedia policy and handles rate limiting.

import hashlib
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.core.api.app.routes.apps_api import (
    SessionOrApiKeyAuth,
    charge_credits_via_internal_api,
)
from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.wikipedia.wikipedia_api import (
    fetch_page_summary,
    fetch_wikidata_entity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/wikipedia", tags=["Wikipedia"])

# Credit cost per API-key request to the Wikipedia proxy (session-cookie callers are free)
CREDITS_PER_REQUEST = 1


async def _charge_if_api_key(auth_info: Dict[str, Any], skill_id: str) -> None:
    """Charge 1 credit if the request is authenticated via API key.
    Web-app session cookie requests are free (api_key_hash is None)."""
    api_key_hash = auth_info.get("api_key_hash")
    if not api_key_hash:
        return  # session cookie — free
    user_id = auth_info.get("user_id")
    if not user_id:
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
@limiter.limit("60/minute")
async def wikipedia_summary(
    request: Request,
    title: str = Query(..., min_length=1, max_length=300, description="Canonical Wikipedia article title"),
    language: str = Query("en", min_length=2, max_length=5, description="Wikipedia language code"),
    auth_info: Dict[str, Any] = SessionOrApiKeyAuth,
) -> JSONResponse:
    """
    Proxy the Wikipedia REST API page summary endpoint.
    Returns title, description, extract, thumbnail, original image, Wikidata QID.

    Auth: session cookie (free) or API key (1 credit per request).
    """
    if not all(c.isalnum() or c == "-" for c in language):
        raise HTTPException(status_code=400, detail="Invalid language code")

    try:
        data = await fetch_page_summary(title=title, language=language)
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] summary fetch error for '{title}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia summary")

    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")

    # Charge credit only for API-key callers (post-fetch so we don't bill on failures)
    await _charge_if_api_key(auth_info, skill_id="wikipedia_summary")

    return JSONResponse(content=data)


@router.get("/wikidata/{qid}")
@limiter.limit("60/minute")
async def wikidata_entity(
    request: Request,
    qid: str,
    auth_info: Dict[str, Any] = SessionOrApiKeyAuth,
) -> JSONResponse:
    """
    Proxy a Wikidata entity lookup (structured claims, labels, descriptions).
    QID must match the Wikidata format (Q followed by digits).

    Auth: session cookie (free) or API key (1 credit per request).
    """
    if not qid.startswith("Q") or not qid[1:].isdigit() or len(qid) > 20:
        raise HTTPException(status_code=400, detail="Invalid QID")

    try:
        data = await fetch_wikidata_entity(qid=qid)
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] wikidata fetch error for '{qid}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikidata entity")

    if data is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    await _charge_if_api_key(auth_info, skill_id="wikidata_entity")

    return JSONResponse(content=data)
