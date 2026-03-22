"""
Favicon Proxy Endpoint

Fetches, resizes, and caches favicons for websites.
Provides privacy by proxying favicon requests through the preview server.

Endpoint: GET /api/v1/favicon?url={website_url}

Features:
- Always resizes favicons to 48x48px (2x retina for 24px display containers)
- Converts to WebP format (best compression, supports transparency, 97%+ browser support)
- Caches processed favicons for 7 days
- Falls back to Google Favicon Service when direct fetch fails
- ETag support for conditional requests (enables browser caching validation)
"""

import logging
import hashlib

from fastapi import APIRouter, Query, Response, HTTPException, Request

from ..services.cache_service import cache_service
from ..services.fetch_service import fetch_service, FetchError
from ..services.image_service import image_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["favicon"])

# Standard favicon size: 48px (2x retina for 24px display containers)
FAVICON_SIZE = 48


def _generate_etag(data: bytes) -> str:
    """
    Generate an ETag from image data using MD5 hash.
    ETag enables browser conditional requests (If-None-Match) for efficient caching.
    """
    return f'"{hashlib.md5(data).hexdigest()}"'


@router.get("/favicon")
async def get_favicon(
    request: Request,
    url: str = Query(..., description="Website URL to fetch favicon for"),
    refresh: bool = Query(False, description="Force refresh from source (bypass cache)")
) -> Response:
    """
    Fetch, resize, and proxy a website's favicon.
    
    This endpoint fetches the favicon for a given website URL, resizes it to
    48x48px, and returns it as WebP. Favicons are cached on disk for 7 days.
    
    **Browser Caching:**
    - Returns ETag for conditional request support
    - Supports If-None-Match header for 304 Not Modified responses
    - Cache-Control enables browser caching for 7 days
    
    Benefits:
    - Privacy: Hides user's IP from target website
    - Performance: Cached favicons load faster, 304 responses reduce bandwidth
    - Consistency: All favicons returned at 48x48px (2x retina for 24px display)
    - Efficiency: WebP format (best compression, supports transparency, 97%+ browser support)
    - Reliability: Google Favicon Service fallback for sites without favicons
    
    Args:
        url: Website URL (e.g., "https://example.com" or "example.com")
        refresh: If True, bypasses cache and fetches fresh from source
        
    Returns:
        Favicon image as 48x48px WebP with appropriate headers
        
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
            favicon_bytes, content_type = cached
            etag = _generate_etag(favicon_bytes)
            
            # Check If-None-Match for conditional request
            # Returns 304 if client already has this exact content
            if_none_match = request.headers.get("if-none-match")
            if if_none_match and if_none_match == etag:
                logger.debug(f"[Favicon] 304 Not Modified for {url[:50]}... (ETag match)")
                return Response(
                    status_code=304,
                    headers={
                        "Cache-Control": "public, max-age=604800, immutable",
                        "ETag": etag,
                        "X-Cache": "HIT"
                    }
                )
            
            logger.debug(f"[Favicon] Returning cached favicon for {url[:50]}...")
            return Response(
                content=favicon_bytes,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=604800, immutable",  # 7 days, immutable
                    "ETag": etag,
                    "X-Cache": "HIT"
                }
            )
    
    # Fetch favicon from source
    try:
        raw_favicon_bytes, original_content_type = await fetch_service.fetch_favicon(url)
        
        logger.debug(f"[Favicon] Fetched raw favicon ({len(raw_favicon_bytes)} bytes, {original_content_type}) for {url[:50]}...")
        
        # Process favicon: resize to 48x48px and convert to WebP
        # WebP has best compression, supports transparency, and 97%+ browser support
        processed_bytes, output_content_type = image_service.process_image(
            image_data=raw_favicon_bytes,
            content_type=original_content_type,
            max_width=FAVICON_SIZE,
            max_height=FAVICON_SIZE,
            quality=85,
            output_format="webp"  # WebP for best compression with transparency support
        )
        
        # Log size reduction
        size_reduction = len(raw_favicon_bytes) - len(processed_bytes)
        logger.info(
            f"[Favicon] Processed: {len(raw_favicon_bytes)} -> {len(processed_bytes)} bytes "
            f"({size_reduction:+d} bytes) at {FAVICON_SIZE}x{FAVICON_SIZE}px for {url[:50]}..."
        )
        
        # Cache the processed result
        cache_service.set_favicon(url, processed_bytes, output_content_type)
        
        # Generate ETag for the new content
        etag = _generate_etag(processed_bytes)
        
        return Response(
            content=processed_bytes,
            media_type=output_content_type,
            headers={
                "Cache-Control": "public, max-age=604800, immutable",  # 7 days, immutable for better client caching
                "ETag": etag,
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

