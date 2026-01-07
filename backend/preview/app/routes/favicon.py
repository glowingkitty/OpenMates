"""
Favicon Proxy Endpoint

Fetches, resizes, and caches favicons for websites.
Provides privacy by proxying favicon requests through the preview server.

Endpoint: GET /api/v1/favicon?url={website_url}

Features:
- Always resizes favicons to 48x48px (2x retina for 24px display containers)
- Converts to PNG format for efficient storage of small images with transparency
- Caches processed favicons for 7 days
- Falls back to Google Favicon Service when direct fetch fails
"""

import logging

from fastapi import APIRouter, Query, Response, HTTPException

from ..services.cache_service import cache_service
from ..services.fetch_service import fetch_service, FetchError
from ..services.image_service import image_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["favicon"])

# Standard favicon size: 48px (2x retina for 24px display containers)
FAVICON_SIZE = 48


@router.get("/favicon")
async def get_favicon(
    url: str = Query(..., description="Website URL to fetch favicon for"),
    refresh: bool = Query(False, description="Force refresh from source (bypass cache)")
) -> Response:
    """
    Fetch, resize, and proxy a website's favicon.
    
    This endpoint fetches the favicon for a given website URL, resizes it to
    48x48px, and returns it as PNG. Favicons are cached on disk for 7 days.
    
    Benefits:
    - Privacy: Hides user's IP from target website
    - Performance: Cached favicons load faster
    - Consistency: All favicons returned at 48x48px (2x retina for 24px display)
    - Efficiency: PNG format for small images with transparency
    - Reliability: Google Favicon Service fallback for sites without favicons
    
    Args:
        url: Website URL (e.g., "https://example.com" or "example.com")
        refresh: If True, bypasses cache and fetches fresh from source
        
    Returns:
        Favicon image as 48x48px PNG with appropriate headers
        
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
                    "Cache-Control": "public, max-age=604800, immutable",  # 7 days, immutable
                    "X-Cache": "HIT"
                }
            )
    
    # Fetch favicon from source
    try:
        raw_favicon_bytes, original_content_type = await fetch_service.fetch_favicon(url)
        
        logger.debug(f"[Favicon] Fetched raw favicon ({len(raw_favicon_bytes)} bytes, {original_content_type}) for {url[:50]}...")
        
        # Process favicon: resize to 48x48px and convert to PNG
        # PNG is efficient for small images and supports transparency
        processed_bytes, output_content_type = image_service.process_image(
            image_data=raw_favicon_bytes,
            content_type=original_content_type,
            max_width=FAVICON_SIZE,
            max_height=FAVICON_SIZE,
            quality=85,
            output_format="png"  # PNG for small images with potential transparency
        )
        
        # Log size reduction
        size_reduction = len(raw_favicon_bytes) - len(processed_bytes)
        logger.info(
            f"[Favicon] Processed: {len(raw_favicon_bytes)} -> {len(processed_bytes)} bytes "
            f"({size_reduction:+d} bytes) at {FAVICON_SIZE}x{FAVICON_SIZE}px for {url[:50]}..."
        )
        
        # Cache the processed result
        cache_service.set_favicon(url, processed_bytes, output_content_type)
        
        return Response(
            content=processed_bytes,
            media_type=output_content_type,
            headers={
                "Cache-Control": "public, max-age=604800, immutable",  # 7 days, immutable for better client caching
                "X-Cache": "MISS",
                "X-Original-Size": str(len(raw_favicon_bytes)),
                "X-Processed-Size": str(len(processed_bytes))
            }
        )
        
    except FetchError as e:
        logger.warning(f"[Favicon] Fetch error for {url[:50]}...: {e.message}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"[Favicon] Unexpected error for {url[:50]}...: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

