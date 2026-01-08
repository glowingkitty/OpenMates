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

SECURITY: Text fields (title, description, channel_name) are sanitized for prompt
injection attacks before being returned. This protects against malicious video
metadata that could manipulate LLMs when users paste YouTube links.

Two-layer defense:
1. ASCII smuggling protection (character-level)
2. LLM-based prompt injection detection (semantic-level)

See: docs/architecture/prompt_injection_protection.md
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

from ..config import settings
from .cache_service import cache_service
from .content_sanitization import sanitize_metadata_fields

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
    - Channel name, ID, and thumbnail (profile picture)
    - Duration, view count, like count
    - Published date
    
    Channel thumbnails require a separate API call (channels.list) since the videos.list
    endpoint only returns channel name and ID, not the channel's profile picture.
    Channel metadata is cached separately with the same TTL as video metadata.
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
        
        SECURITY: Text fields (title, description, channel_name) are sanitized for
        prompt injection attacks before caching and returning. This protects against
        malicious video metadata that could manipulate LLMs.
        
        Args:
            url_or_id: YouTube video URL or video ID
            use_cache: Whether to use cached metadata (default: True)
            
        Returns:
            Metadata dictionary with keys:
            - video_id: YouTube video ID
            - url: Canonical YouTube watch URL
            - title: Video title (sanitized)
            - description: Video description (truncated, sanitized)
            - channel_name: Channel name (sanitized)
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
        log_prefix = f"[YouTubeService][{video_id}] "
        
        # Check cache first
        # Cached metadata is already sanitized (sanitization happens before caching)
        if use_cache:
            # Reuse metadata cache with youtube: prefix
            cached = cache_service.get_metadata(cache_key)
            if cached:
                logger.info(f"{log_prefix}CACHE_HIT")
                return cached
        
        # Cache miss - fetch from YouTube API
        logger.info(f"{log_prefix}CACHE_MISS - fetching metadata...")
        
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
                logger.error(f"{log_prefix}API quota exceeded or key invalid: {response.text}")
                raise YouTubeServiceError(
                    "YouTube API quota exceeded or invalid API key",
                    503
                )
            
            if response.status_code != 200:
                logger.error(f"{log_prefix}API error {response.status_code}: {response.text}")
                raise YouTubeServiceError(
                    f"YouTube API error: {response.status_code}",
                    502
                )
            
            data = response.json()
            
            # Check if video was found
            if not data.get("items"):
                logger.warning(f"{log_prefix}Video not found")
                raise YouTubeServiceError(
                    f"YouTube video not found: {video_id}",
                    404
                )
            
            # Parse response
            item = data["items"][0]
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            statistics = item.get("statistics", {})
            
            # Build metadata response (raw values before sanitization)
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
            
            # ==================================================================
            # SECURITY: Sanitize text fields for prompt injection protection
            # ==================================================================
            # Title, description, and channel_name could contain malicious
            # instructions targeting LLMs. We sanitize these fields before
            # caching/returning. Thumbnail URLs are NOT sanitized (they're URLs,
            # not text that will be processed by LLMs).
            #
            # NOTE: Using batch sanitization - all fields are processed in a
            # SINGLE LLM API call for efficiency.
            # ==================================================================
            
            logger.info(f"{log_prefix}Sanitizing text fields for prompt injection protection...")
            
            # Batch sanitize all text fields in a SINGLE API call
            metadata = await sanitize_metadata_fields(
                metadata,
                text_fields=["title", "description", "channel_name"],
                log_prefix=log_prefix
            )
            
            # Cache the sanitized result
            cache_service.set_metadata(
                cache_key,
                metadata,
                ttl=settings.youtube_cache_ttl_seconds
            )
            
            logger.info(
                f"{log_prefix}Fetched, sanitized, and cached: "
                f"'{(metadata.get('title') or 'N/A')[:40]}...'"
            )
            
            return metadata
            
        except httpx.TimeoutException:
            logger.error(f"{log_prefix}Timeout fetching video")
            raise YouTubeServiceError("YouTube API timeout", 504)
        except httpx.RequestError as e:
            logger.error(f"{log_prefix}Request error: {e}")
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
    
    async def get_channel_metadata(self, channel_id: str, use_cache: bool = True) -> Optional[dict]:
        """
        Get metadata for a YouTube channel (primarily for thumbnail/profile picture).
        
        Checks cache first, then fetches from YouTube Data API if not cached.
        Channel thumbnails are small circular profile pictures, useful for displaying
        alongside video metadata.
        
        SECURITY: Text fields (title, description) are sanitized for prompt injection
        attacks before caching and returning.
        
        Args:
            channel_id: YouTube channel ID (e.g., "UCuAXFkgsw1L7xaCfnd5JJOw")
            use_cache: Whether to use cached metadata (default: True)
            
        Returns:
            Channel metadata dictionary with keys:
            - channel_id: YouTube channel ID
            - title: Channel name (sanitized)
            - description: Channel description (truncated, sanitized)
            - thumbnails: Dict of thumbnail URLs (default, medium, high)
            - custom_url: Custom channel URL handle (e.g., "@RickAstleyYT")
            
            Returns None if channel not found or API error (fails silently to not break video preview)
        """
        if not channel_id:
            logger.warning("[YouTubeService] get_channel_metadata called with empty channel_id")
            return None
        
        # Check if API key is configured
        if not settings.youtube_api_key:
            logger.debug("[YouTubeService] No YouTube API key - skipping channel metadata fetch")
            return None
        
        # Cache key for channel metadata (separate from video metadata)
        cache_key = f"youtube:channel:{channel_id}"
        log_prefix = f"[YouTubeService][channel:{channel_id}] "
        
        # Check cache first
        # Cached metadata is already sanitized (sanitization happens before caching)
        if use_cache:
            cached = cache_service.get_metadata(cache_key)
            if cached:
                logger.info(f"{log_prefix}CACHE_HIT")
                return cached
        
        # Cache miss - fetch from YouTube API
        logger.info(f"{log_prefix}CACHE_MISS - fetching metadata...")
        
        try:
            # Call YouTube Data API v3 channels.list endpoint
            # Request snippet part for channel name, description, thumbnails
            # Cost: 1 quota unit
            response = await self._client.get(
                f"{self.API_BASE_URL}/channels",
                params={
                    "part": "snippet",
                    "id": channel_id,
                    "key": settings.youtube_api_key
                }
            )
            
            # Handle API errors - fail silently for channel metadata
            # (video preview should still work without channel thumbnail)
            if response.status_code == 403:
                logger.warning(f"{log_prefix}API quota exceeded or key invalid")
                return None
            
            if response.status_code != 200:
                logger.warning(f"{log_prefix}API error {response.status_code}")
                return None
            
            data = response.json()
            
            # Check if channel was found
            if not data.get("items"):
                logger.warning(f"{log_prefix}Channel not found")
                return None
            
            # Parse response
            item = data["items"][0]
            snippet = item.get("snippet", {})
            
            # Build channel metadata response (raw values before sanitization)
            # Channel thumbnails are always circular profile pictures in these sizes:
            # - default: 88x88
            # - medium: 240x240
            # - high: 800x800
            channel_metadata = {
                "channel_id": channel_id,
                "title": snippet.get("title"),
                "description": self._truncate_description(snippet.get("description", ""), max_length=200),
                "thumbnails": self._extract_thumbnails(snippet.get("thumbnails", {})),
                "custom_url": snippet.get("customUrl"),  # e.g., "@RickAstleyYT"
            }
            
            # ==================================================================
            # SECURITY: Sanitize text fields for prompt injection protection
            # NOTE: Using batch sanitization - all fields in a SINGLE API call
            # ==================================================================
            
            logger.info(f"{log_prefix}Sanitizing text fields...")
            
            # Batch sanitize all text fields in a SINGLE API call
            channel_metadata = await sanitize_metadata_fields(
                channel_metadata,
                text_fields=["title", "description"],
                log_prefix=log_prefix
            )
            
            # Cache the sanitized result (same TTL as video metadata)
            cache_service.set_metadata(
                cache_key,
                channel_metadata,
                ttl=settings.youtube_cache_ttl_seconds
            )
            
            logger.info(
                f"{log_prefix}Fetched, sanitized, and cached: "
                f"'{(channel_metadata.get('title') or 'N/A')[:30]}...'"
            )
            
            return channel_metadata
            
        except httpx.TimeoutException:
            logger.warning(f"{log_prefix}Timeout fetching channel")
            return None
        except httpx.RequestError as e:
            logger.warning(f"{log_prefix}Request error: {e}")
            return None
        except Exception as e:
            # Log unexpected errors but don't crash - channel metadata is supplementary
            logger.error(f"{log_prefix}Unexpected error: {e}", exc_info=True)
            return None
    
    async def get_video_metadata_with_channel(self, url_or_id: str, use_cache: bool = True) -> dict:
        """
        Get video metadata including channel thumbnail.
        
        This is a convenience method that:
        1. Fetches video metadata (title, duration, thumbnails, etc.)
        2. Fetches channel metadata (thumbnail/profile picture)
        3. Combines them into a single response
        
        The channel thumbnail is useful for rich video previews showing
        the channel's profile picture alongside video information.
        
        Args:
            url_or_id: YouTube video URL or video ID
            use_cache: Whether to use cached metadata (default: True)
            
        Returns:
            Video metadata dict with additional 'channel_thumbnail' key
            (channel_thumbnail is None if channel fetch fails)
            
        Raises:
            YouTubeServiceError: If video not found or API error
        """
        # First, get video metadata (this may raise YouTubeServiceError)
        video_metadata = await self.get_video_metadata(url_or_id, use_cache)
        
        # Then, try to get channel metadata (fails silently)
        channel_id = video_metadata.get("channel_id")
        channel_thumbnail = None
        
        if channel_id:
            channel_metadata = await self.get_channel_metadata(channel_id, use_cache)
            if channel_metadata and channel_metadata.get("thumbnails"):
                # Get best available channel thumbnail (prefer high > medium > default)
                thumbnails = channel_metadata["thumbnails"]
                channel_thumbnail = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default")
                
                logger.debug(
                    f"[YouTubeService] Added channel thumbnail for video {video_metadata.get('video_id')}: "
                    f"{channel_thumbnail[:50] if channel_thumbnail else 'None'}..."
                )
        
        # Add channel thumbnail to video metadata
        video_metadata["channel_thumbnail"] = channel_thumbnail
        
        return video_metadata


# Global YouTube service instance
youtube_service = YouTubeService()


