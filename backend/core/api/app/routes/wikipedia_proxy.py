# backend/core/api/app/routes/wikipedia_proxy.py
#
# Privacy-preserving Wikipedia proxy endpoints.
# The frontend never contacts Wikipedia/Wikidata directly — all requests go
# through this proxy so the user's IP is never exposed to the Wikimedia Foundation.
#
# The backend uses the existing wikipedia provider (backend/shared/providers/wikipedia)
# which already sets a proper User-Agent per Wikimedia policy and handles rate limiting.

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.wikipedia.wikipedia_api import (
    fetch_page_summary,
    fetch_wikidata_entity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/wikipedia", tags=["Wikipedia"])


@router.get("/summary")
@limiter.limit("60/minute")
async def wikipedia_summary(
    request: Request,
    title: str = Query(..., min_length=1, max_length=300, description="Canonical Wikipedia article title"),
    language: str = Query("en", min_length=2, max_length=5, description="Wikipedia language code"),
) -> JSONResponse:
    """
    Proxy the Wikipedia REST API page summary endpoint.
    Returns title, description, extract, thumbnail, original image, Wikidata QID.
    """
    # Basic language code sanitization: only allow alphanumeric + dashes (e.g. "en", "zh-hans")
    if not all(c.isalnum() or c == "-" for c in language):
        raise HTTPException(status_code=400, detail="Invalid language code")

    try:
        data = await fetch_page_summary(title=title, language=language)
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] summary fetch error for '{title}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia summary")

    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")

    return JSONResponse(content=data)


@router.get("/wikidata/{qid}")
@limiter.limit("60/minute")
async def wikidata_entity(request: Request, qid: str) -> JSONResponse:
    """
    Proxy a Wikidata entity lookup (structured claims, labels, descriptions).
    QID must match the Wikidata format (Q followed by digits).
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

    return JSONResponse(content=data)
