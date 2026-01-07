"""
Image Proxy Endpoint

Fetches, processes, and caches images from external URLs.
Provides privacy, performance, and image optimization.

Endpoint: GET /api/v1/image?url={image_url}&max_width=...&max_height=...&quality=...

Features:
- SSRF protection (blocks private/internal IPs)
- Image resizing to max dimensions
- Quality optimization for JPEG/WebP
- Disk-based caching with LRU eviction
- Cache key includes dimensions for multiple variants
- ETag support for conditional requests (enables browser caching validation)
"""

import logging
import hashlib
from typing import Optional

from fastapi import APIRouter, Query, Response, HTTPException, Request

from ..services.cache_service import cache_service
from ..services.fetch_service import fetch_service, FetchError
from ..services.image_service import image_service
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["image"])


def _generate_cache_key(
    url: str,
    max_width: Optional[int],
    max_height: Optional[int],
    quality: Optional[int]
) -> str:
    """
    Generate a cache key that includes image processing parameters.
    
    Different sizes/qualities of the same image get cached separately.
    
    Args:
        url: Image URL
        max_width: Max width parameter
        max_height: Max height parameter
        quality: Quality parameter
        
    Returns:
        Cache key string
    """
    # Normalize parameters (None and 0 both mean "no limit")
    w = max_width if max_width and max_width > 0 else 0
    h = max_height if max_height and max_height > 0 else 0
    q = quality if quality else 0
    
    # Create compound key
    key_parts = f"{url}|w:{w}|h:{h}|q:{q}"
    return hashlib.sha256(key_parts.encode("utf-8")).hexdigest()


def _generate_etag(data: bytes) -> str:
    """
    Generate an ETag from image data using MD5 hash.
    ETag enables browser conditional requests (If-None-Match) for efficient caching.
    """
    return f'"{hashlib.md5(data).hexdigest()}"'


@router.get("/image")
async def get_image(
    request: Request,
    url: str = Query(..., description="Image URL to fetch and proxy"),
    max_width: Optional[int] = Query(
        None,
        ge=0,
        le=4096,
        description="Maximum width in pixels (0 = no limit, default uses server config)"
    ),
    max_height: Optional[int] = Query(
        None,
        ge=0,
        le=4096,
        description="Maximum height in pixels (0 = no limit, default uses server config)"
    ),
    quality: Optional[int] = Query(
        None,
        ge=1,
        le=100,
        description="JPEG/WebP quality 1-100 (default: 85)"
    ),
    format: Optional[str] = Query(
        None,
        description="Output format: jpeg, png, webp (default: auto-detect)"
    ),
    refresh: bool = Query(False, description="Force refresh from source (bypass cache)")
) -> Response:
    """
    Fetch, process, and proxy an image.
    
    This endpoint fetches an image from the given URL, optionally resizes it,
    and returns the processed result. Images are cached on disk to improve
    performance and reduce load on source servers.
    
    **Privacy Benefits:**
    - User's IP is hidden from the target server
    - No tracking cookies or referrers sent
    
    **Performance Benefits:**
    - Images are cached on disk (LRU eviction at 1GB)
    - Resized images are cached separately
    - 7-day cache TTL
    
    **Image Processing:**
    - Resize to max_width/max_height while maintaining aspect ratio
    - Quality adjustment for JPEG/WebP compression
    - Format conversion (auto-detects best format)
    - SVG images are passed through without processing
    
    Args:
        url: Image URL to fetch
        max_width: Maximum width in pixels (0 or None = use server default, typically 1920)
        max_height: Maximum height in pixels (0 or None = use server default, typically 1080)
        quality: JPEG/WebP quality 1-100 (default: 85)
        format: Force output format (jpeg, png, webp)
        refresh: Bypass cache and fetch fresh from source
        
    Returns:
        Processed image with appropriate content type
        
    Raises:
        400: Invalid URL or parameters
        403: Access to private IP blocked (SSRF protection)
        404: Image not found
        413: Image too large
        415: Unsupported image type
        502: Failed to fetch from source
        504: Request timeout
        
    Example:
        GET /api/v1/image?url=https://example.com/photo.jpg&max_width=800&quality=80
    """
    logger.debug(
        f"[Image] Request: url={url[:80]}..., max_width={max_width}, "
        f"max_height={max_height}, quality={quality}, format={format}"
    )
    
    # Validate format parameter
    if format and format.lower() not in ("jpeg", "jpg", "png", "webp"):
        raise HTTPException(
            status_code=400,
            detail="Invalid format. Allowed: jpeg, jpg, png, webp"
        )
    
    # Generate cache key (includes processing parameters)
    cache_key = _generate_cache_key(url, max_width, max_height, quality)
    
    # Check cache first (unless refresh requested)
    if not refresh:
        # We use the image cache but with our custom key
        cached = cache_service.get_image(cache_key)
        if cached:
            image_bytes, content_type = cached
            etag = _generate_etag(image_bytes)
            
            # Check If-None-Match for conditional request
            # Returns 304 if client already has this exact content
            if_none_match = request.headers.get("if-none-match")
            if if_none_match and if_none_match == etag:
                logger.debug(f"[Image] 304 Not Modified for {url[:50]}... (ETag match)")
                return Response(
                    status_code=304,
                    headers={
                        "Cache-Control": "public, max-age=604800, immutable",
                        "ETag": etag,
                        "X-Cache": "HIT"
                    }
                )
            
            logger.debug(f"[Image] Cache HIT for {url[:50]}... (key: {cache_key[:16]})")
            return Response(
                content=image_bytes,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=604800, immutable",  # 7 days, immutable
                    "ETag": etag,
                    "X-Cache": "HIT",
                    "X-Processed": "true"
                }
            )
    
    # Fetch image from source
    try:
        raw_image_bytes, original_content_type = await fetch_service.fetch_image(url)
        
        logger.debug(
            f"[Image] Fetched {len(raw_image_bytes)} bytes ({original_content_type}) "
            f"from {url[:50]}..."
        )
        
        # Process image (resize, optimize)
        processed_bytes, output_content_type = image_service.process_image(
            image_data=raw_image_bytes,
            content_type=original_content_type,
            max_width=max_width,
            max_height=max_height,
            quality=quality,
            output_format=format
        )
        
        # Calculate size reduction
        size_reduction = len(raw_image_bytes) - len(processed_bytes)
        reduction_percent = (size_reduction / len(raw_image_bytes) * 100) if raw_image_bytes else 0
        
        logger.info(
            f"[Image] Processed: {len(raw_image_bytes)} -> {len(processed_bytes)} bytes "
            f"({reduction_percent:.1f}% reduction) for {url[:50]}..."
        )
        
        # Cache the processed result using our custom key
        # We'll store it in the image cache with the custom key
        cache_service._image_cache.set(
            cache_key, 
            (processed_bytes, output_content_type),
            expire=settings.image_cache_ttl_seconds
        )
        
        # Generate ETag for the new content
        etag = _generate_etag(processed_bytes)
        
        return Response(
            content=processed_bytes,
            media_type=output_content_type,
            headers={
                "Cache-Control": "public, max-age=604800, immutable",  # 7 days, immutable
                "ETag": etag,
                "X-Cache": "MISS",
                "X-Processed": "true",
                "X-Original-Size": str(len(raw_image_bytes)),
                "X-Processed-Size": str(len(processed_bytes))
            }
        )
        
    except FetchError as e:
        logger.warning(f"[Image] Fetch error for {url[:50]}...: {e.message}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"[Image] Unexpected error for {url[:50]}...: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/image/info")
async def get_image_info(
    url: str = Query(..., description="Image URL to get info for")
) -> dict:
    """
    Get information about an image without downloading it.
    
    Useful for checking image dimensions before deciding on resize parameters.
    Note: This still fetches the image to get dimensions, but doesn't cache it.
    
    Args:
        url: Image URL
        
    Returns:
        Dictionary with image info (width, height, content_type, size_bytes)
    """
    try:
        image_bytes, content_type = await fetch_service.fetch_image(url)
        width, height = image_service.get_image_dimensions(image_bytes)
        
        return {
            "url": url,
            "width": width,
            "height": height,
            "content_type": content_type,
            "size_bytes": len(image_bytes)
        }
        
    except FetchError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"[Image] Error getting info for {url[:50]}...: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

