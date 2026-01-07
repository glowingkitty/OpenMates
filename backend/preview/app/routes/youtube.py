"""
YouTube Metadata Endpoint

Fetches video metadata from YouTube Data API v3.
Used for generating rich YouTube video embeds in chat.

Endpoint: GET /api/v1/youtube
         POST /api/v1/youtube

Cost: 1 YouTube API quota unit per request (10,000 units/day free)
With 24-hour caching, this supports 10,000+ unique videos per day.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel

from ..services.youtube_service import youtube_service, YouTubeServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["youtube"])


# ===========================================
# Request/Response Models
# ===========================================

class YouTubeRequest(BaseModel):
    """Request body for YouTube metadata extraction."""
    url: str  # YouTube URL or video ID
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            }
        }


class YouTubeDuration(BaseModel):
    """Duration information for a YouTube video."""
    total_seconds: int
    formatted: str  # e.g., "3:32" or "1:23:45"


class YouTubeThumbnails(BaseModel):
    """Available thumbnail URLs at different resolutions."""
    default: Optional[str] = None   # 120x90
    medium: Optional[str] = None    # 320x180
    high: Optional[str] = None      # 480x360
    standard: Optional[str] = None  # 640x480
    maxres: Optional[str] = None    # 1280x720 (not always available)


class YouTubeResponse(BaseModel):
    """Response body with YouTube video metadata."""
    video_id: str
    url: str  # Canonical YouTube watch URL
    title: Optional[str] = None
    description: Optional[str] = None  # Truncated to ~500 chars
    channel_name: Optional[str] = None
    channel_id: Optional[str] = None
    thumbnails: YouTubeThumbnails
    duration: YouTubeDuration
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    published_at: Optional[str] = None  # ISO 8601 datetime
    
    class Config:
        json_schema_extra = {
            "example": {
                "video_id": "dQw4w9WgXcQ",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Rick Astley - Never Gonna Give You Up",
                "description": "The official video for 'Never Gonna Give You Up' by Rick Astley...",
                "channel_name": "Rick Astley",
                "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
                "thumbnails": {
                    "default": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
                    "medium": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
                    "high": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                    "standard": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg",
                    "maxres": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
                },
                "duration": {
                    "total_seconds": 212,
                    "formatted": "3:32"
                },
                "view_count": 1500000000,
                "like_count": 15000000,
                "published_at": "2009-10-25T06:57:33Z"
            }
        }


# ===========================================
# Endpoints
# ===========================================

@router.post("/youtube", response_model=YouTubeResponse)
async def get_youtube_metadata_post(
    request: YouTubeRequest = Body(...)
) -> YouTubeResponse:
    """
    Extract metadata from a YouTube video URL (POST method).
    
    This endpoint accepts a YouTube URL or video ID and returns:
    - Video title and description
    - Channel name and ID
    - Thumbnails at multiple resolutions
    - Video duration
    - View count and like count
    - Publication date
    
    Metadata is cached for 24 hours to minimize API quota usage.
    
    **API Quota:**
    - Cost: 1 quota unit per unique video (cached for 24 hours)
    - Daily limit: 10,000 units (free tier)
    
    **Supported URL formats:**
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - Just the 11-character video ID
    
    Args:
        request: YouTubeRequest with url field
        
    Returns:
        YouTubeResponse with video metadata
        
    Raises:
        400: Invalid URL or video ID
        404: Video not found
        502: YouTube API error
        503: YouTube API not configured or quota exceeded
        504: YouTube API timeout
        
    Example:
        POST /api/v1/youtube
        {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    """
    url = request.url
    
    logger.debug(f"[YouTube] POST request for URL: {url[:100]}...")
    
    try:
        metadata = await youtube_service.get_video_metadata(url)
        
        logger.debug(
            f"[YouTube] Returning metadata for video {metadata.get('video_id')}: "
            f"title='{(metadata.get('title') or 'N/A')[:30]}...'"
        )
        
        # Convert nested dicts to proper response models
        return YouTubeResponse(
            video_id=metadata["video_id"],
            url=metadata["url"],
            title=metadata.get("title"),
            description=metadata.get("description"),
            channel_name=metadata.get("channel_name"),
            channel_id=metadata.get("channel_id"),
            thumbnails=YouTubeThumbnails(**metadata.get("thumbnails", {})),
            duration=YouTubeDuration(**metadata.get("duration", {"total_seconds": 0, "formatted": "0:00"})),
            view_count=metadata.get("view_count"),
            like_count=metadata.get("like_count"),
            published_at=metadata.get("published_at"),
        )
        
    except YouTubeServiceError as e:
        logger.warning(f"[YouTube] Service error for {url[:50]}...: {e.message}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"[YouTube] Unexpected error for {url[:50]}...: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/youtube", response_model=YouTubeResponse)
async def get_youtube_metadata_get(
    url: str = Query(..., description="YouTube video URL or video ID")
) -> YouTubeResponse:
    """
    Extract metadata from a YouTube video URL (GET method).
    
    Same as POST but accepts URL as query parameter for simpler integration.
    Useful for direct browser testing and simpler client implementations.
    
    Args:
        url: YouTube video URL or 11-character video ID
        
    Returns:
        YouTubeResponse with video metadata
        
    Example:
        GET /api/v1/youtube?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
        GET /api/v1/youtube?url=dQw4w9WgXcQ
    """
    logger.debug(f"[YouTube] GET request for URL: {url[:100]}...")
    
    # Reuse POST handler
    request = YouTubeRequest(url=url)
    return await get_youtube_metadata_post(request)

