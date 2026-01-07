"""
Favicon Proxy Endpoint

Fetches and caches favicons for websites.
Provides privacy by proxying favicon requests through the preview server.

Endpoint: GET /api/v1/favicon?url={website_url}
"""

import logging

from fastapi import APIRouter, Query, Response, HTTPException

from ..services.cache_service import cache_service
from ..services.fetch_service import fetch_service, FetchError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["favicon"])


@router.get("/favicon")
async def get_favicon(
    url: str = Query(..., description="Website URL to fetch favicon for"),
    refresh: bool = Query(False, description="Force refresh from source (bypass cache)")
) -> Response:
    """
    Fetch and proxy a website's favicon.
    
    This endpoint fetches the favicon for a given website URL and returns it.
    Favicons are cached on disk for performance and to reduce load on target servers.
    
    Benefits:
    - Privacy: Hides user's IP from target website
    - Performance: Cached favicons load faster
    - Reliability: Google Favicon Service fallback for sites without favicons
    
    Args:
        url: Website URL (e.g., "https://example.com" or "example.com")
        refresh: If True, bypasses cache and fetches fresh from source
        
    Returns:
        Favicon image with appropriate content type
        
    Raises:
        400: Invalid URL
        404: Favicon not found
        502: Failed to fetch from source
        504: Request timeout
    """
    logger.debug(f"[Favicon] Request for URL: {url[:100]}...")
    
    # Normalize URL (add https:// if missing)
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    
    # Check cache first (unless refresh requested)
    if not refresh:
        cached = cache_service.get_favicon(url)
        if cached:
            logger.debug(f"[Favicon] Returning cached favicon for {url[:50]}...")
            favicon_bytes, content_type = cached
            return Response(
                content=favicon_bytes,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=604800",  # 7 days
                    "X-Cache": "HIT"
                }
            )
    
    # Fetch favicon from source
    try:
        favicon_bytes, content_type = await fetch_service.fetch_favicon(url)
        
        # Cache the result
        cache_service.set_favicon(url, favicon_bytes, content_type)
        
        logger.info(f"[Favicon] Fetched and cached favicon ({len(favicon_bytes)} bytes) for {url[:50]}...")
        
        return Response(
            content=favicon_bytes,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=604800",  # 7 days
                "X-Cache": "MISS"
            }
        )
        
    except FetchError as e:
        logger.warning(f"[Favicon] Fetch error for {url[:50]}...: {e.message}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"[Favicon] Unexpected error for {url[:50]}...: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

