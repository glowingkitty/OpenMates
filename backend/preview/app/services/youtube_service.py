"""
YouTube Service

Fetches video metadata from YouTube Data API v3.
Used for generating rich YouTube video embeds.

Features:
- Extract video ID from various YouTube URL formats
- Fetch video metadata (title, description, thumbnails, channel info, duration)
- Caching to minimize API quota usage (10,000 units/day free, 1 unit per request)

YouTube API Quota:
- videos.list costs 1 quota unit per request
- Default daily quota: 10,000 units (free)
- With caching, this supports 10,000+ unique videos per day
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

from ..config import settings
from .cache_service import cache_service

logger = logging.getLogger(__name__)


class YouTubeServiceError(Exception):
    """Custom exception for YouTube service errors with status codes."""
    
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class YouTubeService:
    """
    Service for fetching and caching YouTube video metadata.
    
    Uses YouTube Data API v3 to fetch video information including:
    - Title and description
    - Thumbnails (multiple resolutions)
    - Channel name and ID
    - Duration, view count, like count
    - Published date
    """
    
    # YouTube Data API v3 base URL
    API_BASE_URL = "https://www.googleapis.com/youtube/v3"
    
    # ===========================================
    # URL Patterns for Video ID Extraction
    # ===========================================
    
    # Standard YouTube URL patterns
    # Supports: youtube.com/watch, youtu.be, youtube.com/embed, youtube.com/v, youtube.com/shorts
    VIDEO_ID_PATTERNS = [
        # youtube.com/watch?v=VIDEO_ID
        r'(?:youtube\.com/watch\?.*v=)([a-zA-Z0-9_-]{11})',
        # youtu.be/VIDEO_ID
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        # youtube.com/embed/VIDEO_ID
        r'(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        # youtube.com/v/VIDEO_ID
        r'(?:youtube\.com/v/)([a-zA-Z0-9_-]{11})',
        # youtube.com/shorts/VIDEO_ID
        r'(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        # youtube-nocookie.com/embed/VIDEO_ID (privacy-enhanced mode)
        r'(?:youtube-nocookie\.com/embed/)([a-zA-Z0-9_-]{11})',
        # Just the video ID (11 characters, starts with allowed chars)
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    
    def __init__(self):
        """Initialize YouTube service with HTTP client."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True
        )
        
        if not settings.youtube_api_key:
            logger.warning(
                "[YouTubeService] No YouTube API key configured. "
                "Set SECRET__YOUTUBE__API_KEY or PREVIEW_YOUTUBE_API_KEY env var. "
                "Get key from: https://console.cloud.google.com/apis/credentials"
            )
        else:
            logger.info("[YouTubeService] Initialized with YouTube API key")
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
        logger.info("[YouTubeService] HTTP client closed")
    
    def extract_video_id(self, url_or_id: str) -> Optional[str]:
        """
        Extract YouTube video ID from URL or return if already an ID.
        
        Supports various YouTube URL formats:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - https://www.youtube.com/v/VIDEO_ID
        - https://www.youtube.com/shorts/VIDEO_ID
        - https://www.youtube-nocookie.com/embed/VIDEO_ID
        - Just the video ID (11 characters)
        
        Args:
            url_or_id: YouTube URL or video ID
            
        Returns:
            11-character video ID or None if extraction fails
        """
        if not url_or_id:
            return None
        
        url_or_id = url_or_id.strip()
        
        # Try each pattern
        for pattern in self.VIDEO_ID_PATTERNS:
            match = re.search(pattern, url_or_id)
            if match:
                video_id = match.group(1)
                logger.debug(f"[YouTubeService] Extracted video ID: {video_id} from: {url_or_id[:50]}...")
                return video_id
        
        # Alternative method: parse URL parameters for ?v= style
        try:
            parsed = urlparse(url_or_id)
            if parsed.hostname and 'youtube' in parsed.hostname:
                query_params = parse_qs(parsed.query)
                if 'v' in query_params and query_params['v']:
                    video_id = query_params['v'][0]
                    if len(video_id) == 11:
                        logger.debug(f"[YouTubeService] Extracted video ID from query: {video_id}")
                        return video_id
        except Exception as e:
            logger.debug(f"[YouTubeService] URL parsing fallback failed: {e}")
        
        logger.warning(f"[YouTubeService] Could not extract video ID from: {url_or_id[:100]}")
        return None
    
    def _parse_duration(self, duration_iso: str) -> dict:
        """
        Parse ISO 8601 duration format to human-readable format.
        
        YouTube returns duration in ISO 8601 format: PT1H2M3S
        - P = Period
        - T = Time
        - H = Hours, M = Minutes, S = Seconds
        
        Args:
            duration_iso: ISO 8601 duration string (e.g., "PT1H2M30S")
            
        Returns:
            Dict with total_seconds and formatted string
        """
        if not duration_iso:
            return {"total_seconds": 0, "formatted": "0:00"}
        
        # Parse PT1H2M30S format
        hours = 0
        minutes = 0
        seconds = 0
        
        # Extract hours
        hour_match = re.search(r'(\d+)H', duration_iso)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Extract minutes
        min_match = re.search(r'(\d+)M', duration_iso)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Extract seconds
        sec_match = re.search(r'(\d+)S', duration_iso)
        if sec_match:
            seconds = int(sec_match.group(1))
        
        total_seconds = hours * 3600 + minutes * 60 + seconds
        
        # Format as human-readable
        if hours > 0:
            formatted = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            formatted = f"{minutes}:{seconds:02d}"
        
        return {
            "total_seconds": total_seconds,
            "formatted": formatted
        }
    
    async def get_video_metadata(self, url_or_id: str, use_cache: bool = True) -> dict:
        """
        Get metadata for a YouTube video.
        
        Checks cache first, then fetches from YouTube Data API if not cached.
        
        Args:
            url_or_id: YouTube video URL or video ID
            use_cache: Whether to use cached metadata (default: True)
            
        Returns:
            Metadata dictionary with keys:
            - video_id: YouTube video ID
            - url: Canonical YouTube watch URL
            - title: Video title
            - description: Video description (truncated)
            - channel_name: Channel name
            - channel_id: Channel ID
            - thumbnails: Dict of thumbnail URLs (default, medium, high, standard, maxres)
            - duration: Duration info (total_seconds, formatted)
            - view_count: Number of views
            - like_count: Number of likes (if available)
            - published_at: Publication date
            
        Raises:
            YouTubeServiceError: If video not found or API error
        """
        # Check if API key is configured
        if not settings.youtube_api_key:
            logger.error("[YouTubeService] YouTube API key not configured")
            raise YouTubeServiceError(
                "YouTube API not configured. Contact administrator.",
                503  # Service Unavailable
            )
        
        # Extract video ID
        video_id = self.extract_video_id(url_or_id)
        if not video_id:
            raise YouTubeServiceError(
                f"Could not extract YouTube video ID from: {url_or_id[:100]}",
                400
            )
        
        # Normalize URL for caching
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        cache_key = f"youtube:{video_id}"
        
        # Check cache first
        if use_cache:
            # Reuse metadata cache with youtube: prefix
            cached = cache_service.get_metadata(cache_key)
            if cached:
                logger.info(f"[YouTubeService] CACHE_HIT for video {video_id}")
                return cached
        
        # Cache miss - fetch from YouTube API
        logger.info(f"[YouTubeService] CACHE_MISS - fetching metadata for video {video_id}")
        
        try:
            # Call YouTube Data API v3 videos.list endpoint
            # Request snippet (title, description, thumbnails, channel) and contentDetails (duration)
            # and statistics (view count, like count)
            # Cost: 1 quota unit
            response = await self._client.get(
                f"{self.API_BASE_URL}/videos",
                params={
                    "part": "snippet,contentDetails,statistics",
                    "id": video_id,
                    "key": settings.youtube_api_key
                }
            )
            
            # Handle API errors
            if response.status_code == 403:
                logger.error(f"[YouTubeService] API quota exceeded or key invalid: {response.text}")
                raise YouTubeServiceError(
                    "YouTube API quota exceeded or invalid API key",
                    503
                )
            
            if response.status_code != 200:
                logger.error(f"[YouTubeService] API error {response.status_code}: {response.text}")
                raise YouTubeServiceError(
                    f"YouTube API error: {response.status_code}",
                    502
                )
            
            data = response.json()
            
            # Check if video was found
            if not data.get("items"):
                logger.warning(f"[YouTubeService] Video not found: {video_id}")
                raise YouTubeServiceError(
                    f"YouTube video not found: {video_id}",
                    404
                )
            
            # Parse response
            item = data["items"][0]
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            statistics = item.get("statistics", {})
            
            # Build metadata response
            metadata = {
                "video_id": video_id,
                "url": canonical_url,
                "title": snippet.get("title"),
                "description": self._truncate_description(snippet.get("description", "")),
                "channel_name": snippet.get("channelTitle"),
                "channel_id": snippet.get("channelId"),
                "thumbnails": self._extract_thumbnails(snippet.get("thumbnails", {})),
                "duration": self._parse_duration(content_details.get("duration", "")),
                "view_count": int(statistics.get("viewCount", 0)) if statistics.get("viewCount") else None,
                "like_count": int(statistics.get("likeCount", 0)) if statistics.get("likeCount") else None,
                "published_at": snippet.get("publishedAt"),
            }
            
            # Cache the result
            cache_service.set_metadata(
                cache_key,
                metadata,
                ttl=settings.youtube_cache_ttl_seconds
            )
            
            logger.info(
                f"[YouTubeService] Fetched and cached metadata for video {video_id}: "
                f"'{(metadata.get('title') or 'N/A')[:40]}...'"
            )
            
            return metadata
            
        except httpx.TimeoutException:
            logger.error(f"[YouTubeService] Timeout fetching video {video_id}")
            raise YouTubeServiceError("YouTube API timeout", 504)
        except httpx.RequestError as e:
            logger.error(f"[YouTubeService] Request error: {e}")
            raise YouTubeServiceError(f"YouTube API request failed: {e}", 502)
    
    def _truncate_description(self, description: str, max_length: int = 500) -> str:
        """
        Truncate description to reasonable length for preview.
        
        Args:
            description: Full video description
            max_length: Maximum characters to return
            
        Returns:
            Truncated description with ellipsis if needed
        """
        if not description:
            return ""
        
        # Remove excessive newlines
        description = re.sub(r'\n{3,}', '\n\n', description)
        
        if len(description) <= max_length:
            return description.strip()
        
        # Truncate at word boundary
        truncated = description[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length // 2:
            truncated = truncated[:last_space]
        
        return truncated.strip() + "..."
    
    def _extract_thumbnails(self, thumbnails: dict) -> dict:
        """
        Extract thumbnail URLs from YouTube API response.
        
        YouTube provides thumbnails in various resolutions:
        - default: 120x90
        - medium: 320x180
        - high: 480x360
        - standard: 640x480
        - maxres: 1280x720 (not always available)
        
        Args:
            thumbnails: Thumbnails object from YouTube API
            
        Returns:
            Dict with available thumbnail URLs
        """
        result = {}
        
        for size in ["default", "medium", "high", "standard", "maxres"]:
            if size in thumbnails and thumbnails[size].get("url"):
                result[size] = thumbnails[size]["url"]
        
        return result


# Global YouTube service instance
youtube_service = YouTubeService()


