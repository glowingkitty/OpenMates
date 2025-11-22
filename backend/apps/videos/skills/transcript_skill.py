# backend/apps/videos/skills/transcript_skill.py
#
# YouTube transcript skill implementation.
# Provides functionality to fetch YouTube video transcripts via Oxylabs proxy
# and retrieve video metadata via YouTube Data API.
#
# This skill:
# 1. Extracts video ID from YouTube URL
# 2. Fetches transcript using youtube-transcript-api through Oxylabs proxy
# 3. Fetches video metadata (title, description, views, likes, etc.) via YouTube Data API
# 4. Returns both transcript and metadata for LLM processing

import logging
import os
import time
import asyncio
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs, quote_plus
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content

# YouTube transcript API imports
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import GenericProxyConfig
    from youtube_transcript_api.formatters import TextFormatter
    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("youtube-transcript-api not available. Install with: pip install youtube-transcript-api")

# HTTP client for YouTube Data API and proxy testing
import httpx

logger = logging.getLogger(__name__)


class TranscriptRequest(BaseModel):
    """
    Request model for transcript skill.
    Supports multiple video URLs in a single request for parallel processing.
    """
    # Multiple video URLs (standard format per REST API architecture)
    requests: List[Dict[str, Any]] = Field(
        ...,
        description="Array of transcript request objects. Each object must contain 'url' (YouTube video URL) and can include optional parameters (languages) with defaults from schema."
    )


class VideoMetadata(BaseModel):
    """Video metadata model from YouTube Data API."""
    video_id: str
    title: str
    description: Optional[str] = None
    channel_title: Optional[str] = None
    channel_id: Optional[str] = None
    published_at: Optional[str] = None
    duration: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    thumbnail_url: Optional[str] = None


class TranscriptResult(BaseModel):
    """Individual transcript result model."""
    video_id: str
    url: str
    transcript: Optional[str] = None
    word_count: Optional[int] = None
    language: Optional[str] = None
    is_generated: Optional[bool] = None
    metadata: Optional[VideoMetadata] = None
    error: Optional[str] = None
    success: bool = False


class TranscriptResponse(BaseModel):
    """Response model for transcript skill."""
    # Results are returned directly (not nested in 'previews')
    # The main_processor will extract these and structure them as app_skill_use.output
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of transcript results. These will be flattened and encoded to TOON format by main_processor."
    )
    provider: str = Field(
        default="YouTube Transcript API + YouTube Data API",
        description="The providers used (e.g., 'YouTube Transcript API + YouTube Data API')"
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on transcript results"
    )
    error: Optional[str] = Field(None, description="Error message if transcript fetch failed")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "metadata.thumbnail_url"
        ],
        description="List of field paths (supports dot notation) that should be excluded from LLM inference to reduce token usage. These fields are preserved in chat history for UI rendering but filtered out before sending to LLM."
    )
    preview_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Preview data for frontend rendering. This is skill-specific metadata for UI display (e.g., video_count, success_count, etc.). Does NOT include actual results - those are in 'results' field."
    )


class TranscriptSkill(BaseSkill):
    """
    YouTube transcript skill that fetches video transcripts via Oxylabs proxy
    and retrieves video metadata via YouTube Data API.
    
    Supports multiple video URLs in a single request, processing them in parallel.
    Each video is processed independently and results are combined.
    
    ARCHITECTURE DECISION: Direct Async Execution vs Celery Tasks
    ==============================================================
    
    This skill executes directly in the FastAPI route handler (app-videos container) using
    async/await, rather than dispatching to a Celery task. This is an intentional
    architectural decision for the following reasons:
    
    1. **Performance & Latency**
       - Transcript fetching is a quick operation (typically 1-3 seconds per video)
       - Direct async execution has ~0ms overhead vs Celery's ~50-200ms overhead
       - Users expect immediate results for transcript requests
    
    2. **Non-Blocking Concurrency**
       - The execute() method uses async/await, making it non-blocking
       - FastAPI's event loop can handle multiple concurrent requests efficiently
       - During I/O operations (HTTP calls to YouTube APIs, proxy requests), the
         event loop yields control, allowing other requests to be processed
       - This is NOT blocking - multiple requests are processed concurrently
    
    3. **I/O-Bound Nature**
       - Transcript fetching is primarily I/O-bound (network calls, not CPU-intensive)
       - Async I/O is perfectly suited for this use case
       - No CPU-bound work that would benefit from separate worker processes
    
    4. **Simplicity**
       - Direct execution is simpler: no task queue, no polling, no result storage
       - Easier to debug and monitor (logs appear directly in app-videos)
       - Fewer moving parts = fewer failure points
    
    Current Implementation:
    ----------------------
    - Executes in: app-videos (FastAPI container)
    - Execution model: Direct async execution via async/await
    - Concurrency: Handled by FastAPI's async event loop
    - Blocking: NO - async I/O operations yield control to event loop
    - Scalability: Excellent - FastAPI handles thousands of concurrent requests
    """
    
    def __init__(self,
                 app,  # BaseApp instance - required by BaseSkill
                 app_id: str,
                 skill_id: str,
                 skill_name: str,
                 skill_description: str,
                 stage: str = "development",
                 full_model_reference: Optional[str] = None,
                 pricing_config: Optional[Dict[str, Any]] = None,
                 celery_producer: Optional[Celery] = None,
                 skill_operational_defaults: Optional[Dict[str, Any]] = None
                 ):
        """
        Initialize TranscriptSkill.
        
        Args:
            app: BaseApp instance - required by BaseSkill
            app_id: The ID of the app this skill belongs to
            skill_id: Unique identifier for this skill
            skill_name: Display name for the skill
            skill_description: Description of what the skill does
            stage: Deployment stage (development/production)
            full_model_reference: Optional model reference if skill uses a specific model
            pricing_config: Optional pricing configuration for this skill
            celery_producer: Optional Celery instance for async task processing
            skill_operational_defaults: Optional skill-specific operational defaults from app.yml
        """
        # Call BaseSkill constructor with all required parameters
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer
        )
        
        # Store skill_operational_defaults if provided
        if skill_operational_defaults:
            logger.debug(f"TranscriptSkill '{self.skill_name}' received operational_defaults: {skill_operational_defaults}")
        
        # Initialize secrets manager (will be injected in execute method)
        self.secrets_manager: Optional[SecretsManager] = None
        
        # Check if youtube-transcript-api is available
        if not YOUTUBE_TRANSCRIPT_AVAILABLE:
            logger.error("youtube-transcript-api is not installed. Transcript skill will not work properly.")
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """
        Extract YouTube video ID from URL.
        
        Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://m.youtube.com/watch?v=VIDEO_ID
        
        Args:
            url: YouTube video URL
            
        Returns:
            Video ID if found, None otherwise
        """
        try:
            parsed = urlparse(url)
            if parsed.hostname and "youtube" in parsed.hostname:
                # Standard YouTube URL: https://www.youtube.com/watch?v=VIDEO_ID
                video_id = parse_qs(parsed.query).get("v", [None])[0]
                if video_id:
                    return video_id
            if parsed.hostname and "youtu.be" in parsed.hostname:
                # Short YouTube URL: https://youtu.be/VIDEO_ID
                video_id = parsed.path.lstrip("/")
                if video_id:
                    return video_id
            return None
        except Exception as e:
            logger.error(f"Error extracting video ID from URL '{url}': {e}", exc_info=True)
            return None
    
    def _build_oxylabs_proxy_url(self, secrets_manager: SecretsManager) -> Optional[str]:
        """
        Build Oxylabs proxy URL from environment variables.
        
        Follows Oxylabs' "customer-USERNAME-cc-US-city-london-sessid-ABC-sesstime-5"
        pattern, but any of the optional pieces can be omitted.
        
        Args:
            secrets_manager: SecretsManager instance to get Oxylabs credentials
            
        Returns:
            Proxy URL string if credentials are available, None otherwise
        """
        try:
            # Get Oxylabs credentials from secrets manager
            # Note: We need to use async get_secret, but this is a sync method
            # We'll handle this in the async context where we have access to await
            return None  # Will be built in async context
        except Exception as e:
            logger.error(f"Error building Oxylabs proxy URL: {e}", exc_info=True)
            return None
    
    async def _build_oxylabs_proxy_url_async(self, secrets_manager: SecretsManager) -> Optional[str]:
        """
        Build Oxylabs proxy URL from secrets manager (async version).
        
        Args:
            secrets_manager: SecretsManager instance to get Oxylabs credentials
            
        Returns:
            Proxy URL string if credentials are available, None otherwise
        """
        try:
            # Get Oxylabs credentials from secrets manager
            ox_username = await secrets_manager.get_secret(
                secret_path="kv/data/providers/oxylabs",
                secret_key="proxy_username"
            )
            ox_password = await secrets_manager.get_secret(
                secret_path="kv/data/providers/oxylabs",
                secret_key="proxy_password"
            )
            
            if not ox_username or not ox_password:
                logger.debug("Oxylabs credentials not found - proceeding without proxy")
                return None
            
            # Get optional proxy configuration
            ox_country = os.getenv("OX_COUNTRY", "").strip().upper()
            ox_city = os.getenv("OX_CITY", "").strip().lower()
            ox_state = os.getenv("OX_STATE", "").strip().lower()
            ox_sessid = os.getenv("OX_SESSID", "").strip()
            ox_sestime = os.getenv("OX_SESTIME", "").strip()
            ox_host = os.getenv("OX_HOST", "pr.oxylabs.io")
            ox_port = int(os.getenv("OX_PORT", "7777"))  # 7777 = datacenter, 8080 = residential
            
            # Build proxy username with optional parameters
            parts = ["customer", ox_username]
            
            if ox_country:
                parts.append(f"cc-{ox_country}")
            
            if ox_city:
                parts.append(f"city-{ox_city}")
            
            if ox_state:
                parts.append(f"st-{ox_state}")
            
            if ox_sessid:
                parts.append(f"sessid-{ox_sessid}")
            
            if ox_sestime:
                parts.append(f"sesstime-{ox_sestime}")
            
            # Assemble the username part Oxylabs expects
            ox_user = "-".join(parts)
            
            # URL-encode credentials (password may contain special chars)
            auth = f"{quote_plus(ox_user)}:{quote_plus(ox_password)}"
            proxy_url = f"http://{auth}@{ox_host}:{ox_port}"
            
            logger.debug(f"Built Oxylabs proxy URL (host: {ox_host}, port: {ox_port})")
            return proxy_url
            
        except Exception as e:
            logger.warning(f"Error building Oxylabs proxy URL (will proceed without proxy): {e}", exc_info=True)
            return None
    
    def _make_proxy_config(self, proxy_url: Optional[str]) -> Optional[GenericProxyConfig]:
        """
        Create GenericProxyConfig for youtube-transcript-api.
        
        Args:
            proxy_url: Oxylabs proxy URL (or None if no proxy)
            
        Returns:
            GenericProxyConfig instance or None
        """
        if not proxy_url:
            return None
        
        try:
            return GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
        except Exception as e:
            logger.error(f"Error creating proxy config: {e}", exc_info=True)
            return None
    
    async def _fetch_transcript(
        self,
        video_id: str,
        url: str,
        proxy_config: Optional[GenericProxyConfig],
        languages: List[str] = None,
        max_retries: int = 3,
        base_delay: float = 2.0
    ) -> Dict[str, Any]:
        """
        Fetch transcript for a video with exponential back-off retry logic.
        
        This method runs the synchronous youtube-transcript-api calls in a thread pool
        to avoid blocking the async event loop.
        
        Args:
            video_id: YouTube video ID
            url: Original video URL
            proxy_config: Optional proxy configuration for youtube-transcript-api
            languages: List of language codes to try (default: ["en", "de", "es", "fr"])
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds for exponential backoff
            
        Returns:
            Dict with success status, transcript data, or error information
        """
        if languages is None:
            languages = ["en", "de", "es", "fr"]
        
        if not YOUTUBE_TRANSCRIPT_AVAILABLE:
            return {
                "success": False,
                "video_id": video_id,
                "url": url,
                "error": "youtube-transcript-api package not installed"
            }
        
        # Run synchronous transcript fetching in thread pool to avoid blocking
        def _fetch_sync():
            """Synchronous transcript fetching function to run in thread pool."""
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.debug(f"Retry {attempt+1}/{max_retries} for video {video_id} – sleeping {delay:.1f}s")
                        time.sleep(delay)
                    
                    # Create YouTubeTranscriptApi instance with proxy if available
                    if proxy_config:
                        ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
                    else:
                        ytt_api = YouTubeTranscriptApi()
                    
                    # Fetch transcript - API will pick the first available language
                    fetched = ytt_api.fetch(video_id, languages=languages)
                    formatter = TextFormatter()
                    text = formatter.format_transcript(fetched)
                    
                    return {
                        "success": True,
                        "video_id": video_id,
                        "url": url,
                        "transcript": text,
                        "word_count": len(text.split()),
                        "language": fetched.language,
                        "is_generated": fetched.is_generated,
                    }
                except Exception as exc:
                    logger.warning(f"Transcript fetch attempt {attempt+1}/{max_retries} failed for {video_id}: {type(exc).__name__}: {exc}")
                    if attempt == max_retries - 1:
                        return {
                            "success": False,
                            "video_id": video_id,
                            "url": url,
                            "error": str(exc),
                        }
            
            # Should never reach here
            return {
                "success": False,
                "video_id": video_id,
                "url": url,
                "error": "Unknown error after retries"
            }
        
        # Run in thread pool to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, _fetch_sync)
            return result
        except Exception as e:
            logger.error(f"Error in thread pool execution for transcript fetch: {e}", exc_info=True)
            return {
                "success": False,
                "video_id": video_id,
                "url": url,
                "error": f"Thread pool error: {str(e)}"
            }
    
    async def _fetch_metadata(
        self,
        video_id: str,
        youtube_api_key: str
    ) -> Optional[VideoMetadata]:
        """
        Fetch video metadata from YouTube Data API.
        
        Args:
            video_id: YouTube video ID
            youtube_api_key: YouTube Data API key
            
        Returns:
            VideoMetadata object if successful, None otherwise
        """
        try:
            # YouTube Data API v3 endpoint
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "key": youtube_api_key,
                "id": video_id,
                "part": "snippet,statistics,contentDetails"
            }
            
            # Use httpx for async HTTP requests
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            
            if not data.get("items"):
                logger.warning(f"No video found for ID: {video_id}")
                return None
            
            item = data["items"][0]
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            content_details = item.get("contentDetails", {})
            
            # Extract thumbnail URL (prefer high quality, fallback to default)
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = None
            if thumbnails.get("high"):
                thumbnail_url = thumbnails["high"].get("url")
            elif thumbnails.get("medium"):
                thumbnail_url = thumbnails["medium"].get("url")
            elif thumbnails.get("default"):
                thumbnail_url = thumbnails["default"].get("url")
            
            # Parse view count, like count, comment count (may be strings from API)
            view_count = None
            like_count = None
            comment_count = None
            
            try:
                if statistics.get("viewCount"):
                    view_count = int(statistics["viewCount"])
            except (ValueError, TypeError):
                pass
            
            try:
                if statistics.get("likeCount"):
                    like_count = int(statistics["likeCount"])
            except (ValueError, TypeError):
                pass
            
            try:
                if statistics.get("commentCount"):
                    comment_count = int(statistics["commentCount"])
            except (ValueError, TypeError):
                pass
            
            metadata = VideoMetadata(
                video_id=video_id,
                title=snippet.get("title", ""),
                description=snippet.get("description"),
                channel_title=snippet.get("channelTitle"),
                channel_id=snippet.get("channelId"),
                published_at=snippet.get("publishedAt"),
                duration=content_details.get("duration"),  # ISO 8601 duration format
                view_count=view_count,
                like_count=like_count,
                comment_count=comment_count,
                thumbnail_url=thumbnail_url
            )
            
            logger.debug(f"Successfully fetched metadata for video {video_id}: {metadata.title}")
            return metadata
            
        except httpx.HTTPStatusError as e:
            logger.error(f"YouTube Data API HTTP error for video {video_id}: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error fetching metadata for video {video_id}: {e}", exc_info=True)
            return None
    
    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None
    ) -> TranscriptResponse:
        """
        Execute transcript skill.
        
        Always uses 'requests' array format for consistency and parallel processing support.
        Each request in the array specifies its own parameters with defaults defined in the schema.
        
        NOTE: This method executes directly in the FastAPI route handler (not via Celery).
        This is intentional - see class docstring for architecture decision rationale.
        The async/await pattern ensures non-blocking execution and excellent concurrency.
        
        Args:
            requests: Array of transcript request objects. Each object must contain 'url' and can include optional parameters (languages).
            secrets_manager: SecretsManager instance (injected by app)
        
        Returns:
            TranscriptResponse with results and optional follow-up suggestions
        
        Execution Flow:
        --------------
        1. Request received in FastAPI route handler (app-videos container)
        2. This async method is called directly (no Celery dispatch)
        3. I/O operations (YouTube API calls, transcript fetching) use await
        4. During await, FastAPI event loop processes other requests (non-blocking)
        5. Results returned directly to client (no task polling needed)
        
        This approach provides:
        - Lowest latency (no queue overhead)
        - Excellent concurrency (async event loop)
        - Simple architecture (direct execution)
        - Immediate results (no polling required)
        """
        # Use injected secrets_manager or create a new one
        if secrets_manager is None:
            # Try to get from app if available
            if hasattr(self.app, 'secrets_manager') and self.app.secrets_manager:
                secrets_manager = self.app.secrets_manager
            else:
                # Create a new SecretsManager instance
                try:
                    secrets_manager = SecretsManager()
                    await secrets_manager.initialize()
                    logger.debug("TranscriptSkill initialized its own SecretsManager instance")
                except Exception as e:
                    logger.error(f"Failed to initialize SecretsManager for TranscriptSkill: {e}", exc_info=True)
                    return TranscriptResponse(
                        results=[],
                        error="Transcript service configuration error: Failed to initialize secrets manager"
                    )
        
        # Validate requests array
        if not requests or len(requests) == 0:
            logger.error("No requests provided to TranscriptSkill")
            return TranscriptResponse(
                results=[],
                error="No transcript requests provided. 'requests' array must contain at least one request with a 'url' field."
            )
        
        # Validate that all requests have a URL
        for i, req in enumerate(requests):
            if not req.get("url"):
                logger.error(f"Request {i+1} in requests array is missing 'url' field")
                return TranscriptResponse(
                    results=[],
                    error=f"Request {i+1} is missing required 'url' field"
                )
        
        # Get required API keys and build proxy config
        try:
            # Get YouTube Data API key
            youtube_api_key = await secrets_manager.get_secret(
                secret_path="kv/data/providers/google",
                secret_key="youtube_api_key"
            )
            
            if not youtube_api_key:
                logger.warning("YouTube Data API key not found - metadata fetching will be skipped")
            
            # Build Oxylabs proxy URL (if credentials available)
            proxy_url = await self._build_oxylabs_proxy_url_async(secrets_manager)
            proxy_config = self._make_proxy_config(proxy_url)
            
            if proxy_url:
                logger.debug("Oxylabs proxy will be used for transcript fetching")
            else:
                logger.debug("No Oxylabs proxy configured - transcript fetching will use direct connection")
                
        except Exception as e:
            logger.error(f"Error initializing API keys or proxy: {e}", exc_info=True)
            return TranscriptResponse(
                results=[],
                error=f"Configuration error: {str(e)}"
            )
        
        # Process all transcript requests
        all_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        success_count = 0
        failed_count = 0
        
        for i, req in enumerate(requests):
            video_url = req.get("url", "")
            if not video_url:
                errors.append(f"Request {i+1}: Missing 'url' parameter")
                failed_count += 1
                continue
            
            # Extract video ID from URL
            video_id = self._extract_video_id(video_url)
            if not video_id:
                error_msg = f"Request {i+1}: Could not extract video ID from URL '{video_url}'"
                logger.error(error_msg)
                errors.append(error_msg)
                failed_count += 1
                all_results.append({
                    "success": False,
                    "video_id": None,
                    "url": video_url,
                    "error": "Invalid YouTube URL - could not extract video ID"
                })
                continue
            
            logger.info(f"Processing video {i+1}/{len(requests)}: {video_id} ({video_url})")
            
            # Extract optional parameters
            languages = req.get("languages", ["en", "de", "es", "fr"])
            if not isinstance(languages, list):
                languages = ["en", "de", "es", "fr"]
            
            # Fetch transcript and metadata in parallel
            try:
                # Fetch transcript and metadata concurrently
                transcript_task = self._fetch_transcript(
                    video_id=video_id,
                    url=video_url,
                    proxy_config=proxy_config,
                    languages=languages
                )
                
                metadata_task = None
                if youtube_api_key:
                    metadata_task = self._fetch_metadata(
                        video_id=video_id,
                        youtube_api_key=youtube_api_key
                    )
                
                # Wait for both to complete
                transcript_result = await transcript_task
                metadata = None
                if metadata_task:
                    metadata = await metadata_task
                
                # Combine results
                if transcript_result.get("success"):
                    success_count += 1
                    
                    # Build result dict
                    result = {
                        "type": "video_transcript",
                        "video_id": video_id,
                        "url": video_url,
                        "transcript": transcript_result.get("transcript", ""),
                        "word_count": transcript_result.get("word_count", 0),
                        "language": transcript_result.get("language"),
                        "is_generated": transcript_result.get("is_generated", False),
                        "success": True
                    }
                    
                    # Add metadata if available
                    if metadata:
                        result["metadata"] = {
                            "title": metadata.title,
                            "description": metadata.description,
                            "channel_title": metadata.channel_title,
                            "channel_id": metadata.channel_id,
                            "published_at": metadata.published_at,
                            "duration": metadata.duration,
                            "view_count": metadata.view_count,
                            "like_count": metadata.like_count,
                            "comment_count": metadata.comment_count,
                            "thumbnail_url": metadata.thumbnail_url
                        }
                    
                    # Sanitize transcript text before adding to results
                    # This is critical for security - external content must be sanitized
                    transcript_text = result.get("transcript", "")
                    if transcript_text:
                        try:
                            sanitized_transcript = await sanitize_external_content(
                                content=transcript_text,
                                content_type="text",
                                task_id=f"transcript_{video_id}",
                                secrets_manager=secrets_manager
                            )
                            
                            # Check if sanitization failed or was blocked
                            if sanitized_transcript is None:
                                error_msg = f"Content sanitization failed for video {video_id}: sanitization returned None. This indicates a critical security failure."
                                logger.error(error_msg)
                                errors.append(f"Video {video_id}: Content sanitization failed - LLM call failed")
                                failed_count += 1
                                success_count -= 1
                                continue
                            
                            if not sanitized_transcript or not sanitized_transcript.strip():
                                error_msg = f"Content sanitization blocked for video {video_id}: sanitization returned empty. This indicates high prompt injection risk was detected."
                                logger.error(error_msg)
                                errors.append(f"Video {video_id}: Content sanitization blocked - high prompt injection risk detected")
                                failed_count += 1
                                success_count -= 1
                                continue
                            
                            # Update result with sanitized transcript
                            result["transcript"] = sanitized_transcript
                            
                        except Exception as e:
                            error_msg = f"Error sanitizing transcript for video {video_id}: {e}"
                            logger.error(error_msg, exc_info=True)
                            errors.append(f"Video {video_id}: Sanitization error - {str(e)}")
                            # Continue with unsanitized content is NOT safe - fail the request
                            failed_count += 1
                            success_count -= 1
                            continue
                    
                    all_results.append(result)
                    logger.info(f"Successfully processed video {video_id}: {transcript_result.get('word_count', 0)} words, metadata: {'yes' if metadata else 'no'}")
                else:
                    failed_count += 1
                    error_msg = transcript_result.get("error", "Unknown error")
                    errors.append(f"Video {video_id}: {error_msg}")
                    all_results.append({
                        "success": False,
                        "video_id": video_id,
                        "url": video_url,
                        "error": error_msg
                    })
                    logger.warning(f"Failed to fetch transcript for video {video_id}: {error_msg}")
                
            except Exception as e:
                error_msg = f"Video {video_id}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                failed_count += 1
                all_results.append({
                    "success": False,
                    "video_id": video_id,
                    "url": video_url,
                    "error": str(e)
                })
            
            # Be nice to YouTube - a short pause between calls
            if i < len(requests) - 1:
                await asyncio.sleep(1)
        
        # Build preview_data for frontend rendering
        preview_data: Dict[str, Any] = {
            "video_count": len(requests),
            "success_count": success_count,
            "failed_count": failed_count
        }
        
        # Build response
        response = TranscriptResponse(
            results=all_results,
            provider="YouTube Transcript API + YouTube Data API",
            suggestions_follow_up_requests=None,  # Can be added from app.yml if needed
            preview_data=preview_data
        )
        
        # Add error message if there were errors (but still return results if any)
        if errors:
            response.error = "; ".join(errors)
            logger.warning(f"Transcript skill execution completed with {len(errors)} error(s): {response.error}")
        
        logger.info(f"Transcript skill execution completed: {success_count} successful, {failed_count} failed")
        return response

