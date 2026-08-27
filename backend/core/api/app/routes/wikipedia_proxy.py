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

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from backend.core.api.app.routes.apps_api import charge_credits_via_internal_api
from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.wikipedia.wikipedia_api import (
    fetch_page_summary,
    fetch_wikidata_entity,
    normalize_wikipedia_language,
    search_wikipedia_titles,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/wikipedia", tags=["Wikipedia"])

# Credit cost per API-key request to the Wikipedia proxy
CREDITS_PER_REQUEST = 1

# Anonymous (origin-only) rate limit — enforced manually via Redis below, since
# SlowAPI's decorator callable has no access to the request and can't read auth state.
# Authenticated callers (session cookie OR API key) use the 60/minute slowapi cap.
ANON_RATE_LIMIT_PER_MINUTE = 15
WIKIPEDIA_PROXY_CACHE_TTL_SECONDS = 60 * 60
WIKIPEDIA_SHARED_BUDGET_PER_MINUTE = 150
WIKIPEDIA_UPSTREAM_CONCURRENCY = 3
_wikipedia_upstream_semaphore = asyncio.Semaphore(WIKIPEDIA_UPSTREAM_CONCURRENCY)


def _wikipedia_cache_key(kind: str, language: str, identifier: str, limit: Optional[int] = None) -> str:
    normalized = json.dumps(
        {"kind": kind, "language": language, "identifier": identifier.strip(), "limit": limit},
        sort_keys=True,
    )
    return "wikipedia_proxy:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def _cache_client():
    from backend.core.api.app.services.cache import CacheService

    return await CacheService().client


async def _get_cached_payload(cache_key: str) -> Optional[Any]:
    client = await _cache_client()
    if not client:
        return None
    raw = await client.get(cache_key)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def _set_cached_payload(cache_key: str, payload: Any) -> None:
    client = await _cache_client()
    if not client:
        return
    await client.setex(cache_key, WIKIPEDIA_PROXY_CACHE_TTL_SECONDS, json.dumps(payload, ensure_ascii=True))


async def _reserve_shared_wikipedia_budget() -> None:
    client = await _cache_client()
    if not client:
        raise HTTPException(status_code=503, detail="Wikipedia proxy budget store unavailable")
    key = f"wikipedia_proxy_budget:{int(time.time()) // 60}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 90)
    if count > WIKIPEDIA_SHARED_BUDGET_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Wikipedia proxy shared rate limit exceeded")


async def _fetch_cached_wikipedia_payload(cache_key: str, fetcher: Callable[[], Awaitable[Any]]) -> Any:
    try:
        cached = await _get_cached_payload(cache_key)
    except Exception as exc:
        logger.warning("[wikipedia_proxy] cache read failed: %s", exc, exc_info=True)
        cached = None
    if cached is not None:
        return cached

    await _reserve_shared_wikipedia_budget()
    async with _wikipedia_upstream_semaphore:
        payload = await fetcher()

    if payload is not None:
        try:
            await _set_cached_payload(cache_key, payload)
        except Exception as exc:
            logger.warning("[wikipedia_proxy] cache write failed: %s", exc, exc_info=True)
    return payload


def _summary_response_payload(data: dict[str, Any], language: str) -> dict[str, Any]:
    titles = data.get("titles") or {}
    desktop_urls = (data.get("content_urls") or {}).get("desktop") or {}
    thumbnail = data.get("thumbnail") or {}
    return {
        "language": language,
        "page_id": data.get("pageid"),
        "title": data.get("title") or titles.get("normalized") or titles.get("canonical"),
        "canonical_title": titles.get("canonical") or data.get("title"),
        "description": data.get("description") or "",
        "extract": data.get("extract") or "",
        "source_url": desktop_urls.get("page") or data.get("content_urls", {}).get("page", ""),
        "thumbnail_url": thumbnail.get("source") or thumbnail.get("url"),
    }


async def _check_anon_rate_limit(request: Request) -> None:
    """Manually enforce 15/min for anonymous callers (no cookie, no API key).
    Uses a Redis counter keyed by IP. Raises 429 when exceeded."""
    has_cookie = bool(request.cookies.get("auth_refresh_token"))
    auth_header = request.headers.get("Authorization", "")
    has_api_key = auth_header.startswith("Bearer ")
    if has_cookie or has_api_key:
        return  # authenticated — slowapi's 60/min applies

    # Anonymous — apply stricter 15/min per IP
    try:
        from backend.core.api.app.services.cache import CacheService
        from slowapi.util import get_remote_address
        ip = get_remote_address(request) or "unknown"
        # Bucket per current minute so counter auto-rolls
        import time
        bucket = int(time.time()) // 60
        key = f"wiki_anon_rl:{ip}:{bucket}"
        c = await CacheService().client
        if not c:
            return  # Redis unavailable — fail open
        count = await c.incr(key)
        if count == 1:
            await c.expire(key, 90)  # slightly more than 1 minute
        if count > ANON_RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for unauthenticated callers ({ANON_RATE_LIMIT_PER_MINUTE}/min). "
                       f"Log in or use an API key for higher limits.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"[wikipedia_proxy] anon rate check failed (open): {e}")


@router.get("/search")
@limiter.limit("60/minute")
async def wikipedia_search(
    request: Request,
    response: Response,
    query: str = Query(..., min_length=1, max_length=300, description="Wikipedia title search query"),
    language: str = Query("en", min_length=2, max_length=10, description="Wikipedia language code or locale"),
    limit: int = Query(5, ge=1, le=10, description="Maximum number of title results"),
) -> JSONResponse:
    """Search Wikipedia titles without Wikidata or client-side Wikimedia requests."""
    language = normalize_wikipedia_language(language)
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Search query is required")

    auth_info = await _authorize_request(request, response)
    await _check_anon_rate_limit(request)
    cache_key = _wikipedia_cache_key("search", language, normalized_query, limit)

    try:
        results = await _fetch_cached_wikipedia_payload(
            cache_key,
            lambda: search_wikipedia_titles(normalized_query, language=language, limit=limit),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] search fetch error for '{normalized_query}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia search results")

    response_results = [
        result.model_dump(exclude_none=True) if hasattr(result, "model_dump") else result
        for result in (results or [])
    ]
    await _charge_if_api_key(auth_info, skill_id="wikipedia_search")
    return JSONResponse(content={"results": response_results})


async def _authorize_request(request: Request, response: Response) -> Dict[str, Any]:
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
            response=response,
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
@limiter.limit("60/minute")
async def wikipedia_summary(
    request: Request,
    response: Response,
    title: str = Query(..., min_length=1, max_length=300, description="Canonical Wikipedia article title"),
    language: str = Query("en", min_length=2, max_length=5, description="Wikipedia language code"),
) -> JSONResponse:
    """
    Proxy the Wikipedia REST API page summary endpoint.
    Returns title, description, extract, thumbnail, original image, Wikidata QID.

    Auth: trusted Origin OR session cookie (free) OR API key (1 credit per request).
    """
    language = normalize_wikipedia_language(language)

    auth_info = await _authorize_request(request, response)
    await _check_anon_rate_limit(request)
    cache_key = _wikipedia_cache_key("summary", language, title)

    try:
        data = await _fetch_cached_wikipedia_payload(
            cache_key,
            lambda: fetch_page_summary(title=title, language=language),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] summary fetch error for '{title}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia summary")

    if data is None:
        raise HTTPException(status_code=404, detail="Article not found")

    await _charge_if_api_key(auth_info, skill_id="wikipedia_summary")
    return JSONResponse(content=_summary_response_payload(data, language))


@router.get("/wikidata/{qid}")
@limiter.limit("60/minute")
async def wikidata_entity(request: Request, response: Response, qid: str) -> JSONResponse:
    """
    Proxy a Wikidata entity lookup (structured claims, labels, descriptions).
    QID must match the Wikidata format (Q followed by digits).

    Auth: trusted Origin OR session cookie (free) OR API key (1 credit per request).
    """
    if not qid.startswith("Q") or not qid[1:].isdigit() or len(qid) > 20:
        raise HTTPException(status_code=400, detail="Invalid QID")

    auth_info = await _authorize_request(request, response)
    await _check_anon_rate_limit(request)

    try:
        data = await fetch_wikidata_entity(qid=qid)
    except Exception as e:
        logger.warning(f"[wikipedia_proxy] wikidata fetch error for '{qid}': {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Wikidata entity")

    if data is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    await _charge_if_api_key(auth_info, skill_id="wikidata_entity")
    return JSONResponse(content=data)
