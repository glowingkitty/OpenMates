"""
Metadata Extraction Endpoint

Extracts Open Graph and other metadata from websites.
Used for generating rich link previews.

Endpoint: POST /api/v1/metadata
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from ..services.metadata_service import metadata_service
from ..services.fetch_service import FetchError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["metadata"])


class MetadataRequest(BaseModel):
    """Request body for metadata extraction."""
    url: str  # Using str instead of HttpUrl for more lenient validation
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/article"
            }
        }


class MetadataResponse(BaseModel):
    """Response body with extracted metadata."""
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    favicon: Optional[str] = None
    site_name: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/article",
                "title": "Example Article Title",
                "description": "This is an example article description...",
                "image": "https://example.com/og-image.jpg",
                "favicon": "https://example.com/favicon.ico",
                "site_name": "Example.com"
            }
        }


@router.post("/metadata", response_model=MetadataResponse)
async def get_metadata(
    request: MetadataRequest = Body(...)
) -> MetadataResponse:
    """
    Extract metadata from a website URL.
    
    This endpoint fetches the HTML of the given URL and extracts:
    - Title (from og:title, twitter:title, or <title>)
    - Description (from og:description, twitter:description, or meta description)
    - Preview image (from og:image or twitter:image)
    - Favicon URL
    - Site name (from og:site_name or hostname)
    
    Metadata is cached for 24 hours to reduce load on target servers.
    
    **Use Cases:**
    - Generate rich link previews in chat
    - Display website cards in search results
    - Pre-populate bookmark metadata
    
    Args:
        request: MetadataRequest with url field
        
    Returns:
        MetadataResponse with extracted metadata
        
    Raises:
        400: Invalid URL
        403: Access to private IP blocked
        404: Page not found
        502: Failed to fetch page
        504: Request timeout
        
    Example:
        POST /api/v1/metadata
        {"url": "https://github.com/openai/gpt-3"}
    """
    url = request.url
    
    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    
    logger.debug(f"[Metadata] Request for URL: {url[:100]}...")
    
    try:
        metadata = await metadata_service.get_metadata(url)
        
        logger.debug(
            f"[Metadata] Returning metadata for {url[:50]}...: "
            f"title='{(metadata.get('title') or 'N/A')[:30]}...'"
        )
        
        return MetadataResponse(**metadata)
        
    except FetchError as e:
        logger.warning(f"[Metadata] Fetch error for {url[:50]}...: {e.message}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"[Metadata] Unexpected error for {url[:50]}...: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/metadata")
async def get_metadata_get(
    url: str
) -> MetadataResponse:
    """
    GET version of metadata endpoint for simpler integration.
    
    Same as POST but accepts URL as query parameter.
    
    Args:
        url: Website URL to extract metadata from
        
    Returns:
        MetadataResponse with extracted metadata
    """
    # Reuse POST handler
    request = MetadataRequest(url=url)
    return await get_metadata(request)

