# backend/apps/videos/skills/transcript_skill.py
#
# YouTube transcript skill implementation.
# Provides functionality to fetch YouTube video transcripts via Oxylabs proxy.
#
# This skill:
# 1. Extracts video ID from YouTube URL
# 2. Fetches transcript using youtube-transcript-api through Oxylabs proxy
# 3. Returns transcript text for LLM processing

import logging
import os
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, quote_plus
from pydantic import BaseModel, Field, field_validator, ValidationError
from celery import Celery  # For Celery type hinting

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content
from backend.shared.providers.youtube.youtube_metadata import get_video_metadata_batched
from backend.core.api.app.services.creators.revenue_service import CreatorRevenueService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.cache import CacheService
from backend.shared.python_utils.url_normalizer import sanitize_url_remove_fragment

# YouTube transcript API imports
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import GenericProxyConfig
    # TextFormatter removed - we now extract timestamps directly from transcript items
    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("youtube-transcript-api not available. Install with: pip install youtube-transcript-api")

logger = logging.getLogger(__name__)


class TranscriptRequestItem(BaseModel):
    """
    Individual transcript request item with URL validation.
    Validates that the URL is a valid YouTube URL that can have its video ID extracted.
    
    NOTE: YouTube Shorts URLs are NOT supported and will be rejected at validation time.
    """
    url: str = Field(..., description="YouTube video URL (supports watch and youtu.be formats only - Shorts URLs are not supported)")
    languages: Optional[List[str]] = Field(
        default=None,
        description="List of language codes to try for transcript (ISO 639-1, e.g., 'en', 'de', 'es', 'fr'). The API will use the first available language."
    )
    
    @field_validator('url')
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        """
        Validate that the URL is a valid YouTube URL from which we can extract a video ID.
        
        Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://m.youtube.com/watch?v=VIDEO_ID
        
        REJECTS:
        - https://www.youtube.com/shorts/VIDEO_ID (Shorts URLs are not supported)
        
        Args:
            v: The URL string to validate
            
        Returns:
            The validated URL string
            
        Raises:
            ValueError: If the URL is not a valid YouTube URL, is a Shorts URL, or video ID cannot be extracted
        """
        if not v or not isinstance(v, str):
            raise ValueError("URL must be a non-empty string")
        
        # Extract video ID using the same logic as _extract_video_id
        try:
            parsed = urlparse(v)
            
            # EXPLICITLY REJECT Shorts URLs - they are not supported
            if parsed.hostname and "youtube" in parsed.hostname:
                if "/shorts/" in parsed.path:
                    raise ValueError(f"Invalid YouTube URL: '{v}' - YouTube Shorts URLs are not supported. Please use a regular YouTube video URL (youtube.com/watch?v=VIDEO_ID or youtu.be/VIDEO_ID)")
            
            video_id = None
            
            if parsed.hostname and "youtube" in parsed.hostname:
                # Standard YouTube URL: https://www.youtube.com/watch?v=VIDEO_ID
                video_id = parse_qs(parsed.query).get("v", [None])[0]
                if video_id:
                    return v
            
            if parsed.hostname and "youtu.be" in parsed.hostname:
                # Short YouTube URL: https://youtu.be/VIDEO_ID
                video_id = parsed.path.lstrip("/").split("?")[0].split("/")[0]
                if video_id and len(video_id) == 11:  # YouTube video IDs are 11 characters
                    return v
            
            # If we get here, we couldn't extract a valid video ID
            raise ValueError(f"Invalid YouTube URL: '{v}' - could not extract video ID. Supported formats: youtube.com/watch?v=VIDEO_ID, youtu.be/VIDEO_ID. YouTube Shorts URLs are not supported.")
            
        except ValueError:
            # Re-raise ValueError (our validation error)
            raise
        except Exception as e:
            # Wrap other exceptions in ValueError for consistent error handling
            raise ValueError(f"Invalid YouTube URL: '{v}' - error parsing URL: {str(e)}")


class TranscriptRequest(BaseModel):
    """
    Request model for transcript skill.
    Supports multiple video URLs in a single request for parallel processing.
    """
    # Multiple video URLs (standard format per REST API architecture)
    requests: List[TranscriptRequestItem] = Field(
        ...,
        description="Array of transcript request objects. Each object must contain 'url' (YouTube video URL) and can include optional parameters (languages) with defaults from schema."
    )


class TranscriptResult(BaseModel):
    """Individual transcript result model."""
    url: str
    transcript: Optional[str] = None  # Formatted multiline transcript with timestamps: [HH:MM:SS.mmm] text
    word_count: Optional[int] = None
    characters_count: Optional[int] = None
    language: Optional[str] = None
    error: Optional[str] = None


class TranscriptResponse(BaseModel):
    """Response model for transcript skill."""
    # Results are grouped by request id - each entry contains 'id' and 'results' array
    # This structure allows clients to match responses to original requests without redundant data
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' (matching request id) and 'results' array with actual transcript results for that request."
    )
    provider: str = Field(
        default="YouTube Transcript API",
        description="The provider used (e.g., 'YouTube Transcript API')"
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on transcript results"
    )
    error: Optional[str] = Field(None, description="Error message if transcript fetch failed")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash"
        ],
        description="List of field paths (supports dot notation) that should be excluded from LLM inference to reduce token usage. These fields are preserved in chat history for UI rendering but filtered out before sending to LLM."
    )
    # preview_data removed: redundant metadata that can be derived from results
    # preview_data: Optional[Dict[str, Any]] = Field(
    #     None,
    #     description="Preview data for frontend rendering. This is skill-specific metadata for UI display (e.g., video_count, success_count, etc.). Does NOT include actual results - those are in 'results' field."
    # )


class TranscriptSkill(BaseSkill):
    """
    YouTube transcript skill that fetches video transcripts via Oxylabs proxy.
    
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
    
    async def _build_oxylabs_proxy_url_async(self, secrets_manager: SecretsManager, session_suffix: Optional[str] = None) -> Optional[str]:
        """
        Build Oxylabs proxy URL from secrets manager (async version).

        Args:
            secrets_manager: SecretsManager instance to get Oxylabs credentials
            session_suffix: Optional suffix to add to session ID for different IPs (e.g., "retry1", "retry2")

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

            # Generate unique session ID for each attempt to get different IP
            if ox_sessid:
                # If session_suffix provided, append it to get different IP for retries
                if session_suffix:
                    unique_sessid = f"{ox_sessid}-{session_suffix}"
                else:
                    unique_sessid = ox_sessid
                parts.append(f"sessid-{unique_sessid}")
            elif session_suffix:
                # If no base session ID but suffix provided, use just the suffix
                parts.append(f"sessid-{session_suffix}")

            if ox_sestime:
                parts.append(f"sesstime-{ox_sestime}")

            # Assemble the username part Oxylabs expects
            ox_user = "-".join(parts)

            # URL-encode credentials (password may contain special chars)
            auth = f"{quote_plus(ox_user)}:{quote_plus(ox_password)}"
            proxy_url = f"http://{auth}@{ox_host}:{ox_port}"

            logger.debug(f"Built Oxylabs proxy URL (host: {ox_host}, port: {ox_port}, session_suffix: {session_suffix})")
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
    
    def _format_timestamp(self, seconds: float) -> str:
        """
        Format timestamp in seconds to [HH:MM:SS.mmm] format.
        
        Args:
            seconds: Timestamp in seconds (float)
            
        Returns:
            Formatted timestamp string like [00:01:23.456]
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}]"
    
    def _format_transcript_with_timestamps(self, transcript_items: List[Dict[str, Any]]) -> str:
        """
        Format transcript items into a single multiline string with timestamps.
        
        Format: [HH:MM:SS.mmm] text
        
        Args:
            transcript_items: List of transcript items, each with 'text' and 'start' fields
            
        Returns:
            Multiline string with timestamped transcript
        """
        lines = []
        for item in transcript_items:
            timestamp = self._format_timestamp(item['start'])
            text = item['text'].strip()
            # Replace newlines in text with spaces for cleaner formatting
            text = text.replace('\n', ' ')
            lines.append(f"{timestamp} {text}")
        
        return "\n".join(lines)
    
    async def _fetch_transcript(
        self,
        video_id: str,
        url: str,
        secrets_manager: SecretsManager,
        languages: List[str] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Fetch transcript for a video with retry logic using different IP addresses.

        This method runs the synchronous youtube-transcript-api calls in a thread pool
        to avoid blocking the async event loop. Each retry attempt uses a different
        proxy session ID to get a different IP address, eliminating the need for delays.

        Args:
            video_id: YouTube video ID
            url: Original video URL
            secrets_manager: SecretsManager instance to build proxy configs for each retry
            languages: List of language codes to try (default: ["en", "de", "es", "fr"])
            max_retries: Maximum number of retry attempts

        Returns:
            Dict with success status, transcript data, or error information
        """
        if languages is None:
            languages = ["en", "de", "es", "fr"]
        
        if not YOUTUBE_TRANSCRIPT_AVAILABLE:
            return {
                "success": False,
                "url": url,
                "error": "youtube-transcript-api package not installed"
            }

        # Pre-build proxy configs for each retry attempt to get different IPs
        proxy_configs = []
        for attempt in range(max_retries):
            session_suffix = f"retry{attempt}" if attempt > 0 else None
            proxy_url = await self._build_oxylabs_proxy_url_async(secrets_manager, session_suffix)
            proxy_config = self._make_proxy_config(proxy_url)
            proxy_configs.append(proxy_config)

            if proxy_url:
                logger.debug(f"Built proxy config for attempt {attempt+1} with session suffix: {session_suffix}")

        # Run synchronous transcript fetching in thread pool to avoid blocking
        def _fetch_sync():
            """Synchronous transcript fetching function to run in thread pool."""
            for attempt in range(max_retries):
                try:
                    # Use pre-built proxy config for this attempt (different IP for each retry)
                    proxy_config = proxy_configs[attempt]
                    if proxy_config:
                        logger.debug(f"Attempt {attempt+1}/{max_retries}: Using proxy with different session ID (retry{attempt})")
                        ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
                    else:
                        logger.debug(f"Attempt {attempt+1}/{max_retries}: No proxy available, using direct connection")
                        ytt_api = YouTubeTranscriptApi()
                    
                    # Fetch transcript - API will pick the first available language
                    # The fetch() method returns a TranscriptList object containing transcript items
                    # Each item has: text, start (timestamp in seconds), duration (in seconds)
                    fetched = ytt_api.fetch(video_id, languages=languages)
                    
                    # Extract transcript items with timestamps
                    # Each item can be accessed as dict (item['text']) or object (item.text)
                    transcript_items = []
                    transcript_text_parts = []
                    
                    for item in fetched:
                        # Handle both dict and object access patterns
                        text = item['text'] if isinstance(item, dict) else item.text
                        start = item['start'] if isinstance(item, dict) else item.start
                        duration = item['duration'] if isinstance(item, dict) else item.duration
                        
                        transcript_items.append({
                            "text": text,
                            "start": start,  # Start timestamp in seconds
                            "duration": duration  # Duration in seconds
                        })
                        transcript_text_parts.append(text)
                    
                    # Also keep plain text for word/character counting
                    plain_text = " ".join(transcript_text_parts)
                    
                    return {
                        "success": True,
                        "url": url,
                        "transcript_items": transcript_items,  # Raw items - will be formatted outside sync function
                        "plain_text": plain_text,  # Plain text for word/character counting
                        "word_count": len(plain_text.split()),
                        "characters_count": len(plain_text),
                        "language": fetched.language,
                    }
                except Exception as exc:
                    proxy_info = f"(proxy session: retry{attempt})" if proxy_configs[attempt] else "(direct connection)"
                    logger.warning(f"Transcript fetch attempt {attempt+1}/{max_retries} failed for {video_id} {proxy_info}: {type(exc).__name__}: {exc}")
                    if attempt == max_retries - 1:
                        return {
                            "success": False,
                            "url": url,
                            "error": str(exc),
                        }
            
            # Should never reach here
            return {
                "success": False,
                "url": url,
                "error": "Unknown error after retries"
            }
        
        # Run in thread pool to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, _fetch_sync)
            
            # Format transcript with timestamps if fetch was successful
            if result.get("success") and "transcript_items" in result:
                transcript_items = result.pop("transcript_items")
                plain_text = result.pop("plain_text", "")
                
                # Format transcript as multiline string with timestamps
                # Format: [HH:MM:SS.mmm] text (one line per timestamp segment)
                formatted_transcript = self._format_transcript_with_timestamps(transcript_items)
                
                # Update result with formatted transcript (timestamps are now included in the transcript text)
                result["transcript"] = formatted_transcript
            
            return result
        except Exception as e:
            logger.error(f"Error in thread pool execution for transcript fetch: {e}", exc_info=True)
            return {
                "success": False,
                "url": url,
                "error": f"Thread pool error: {str(e)}"
            }
    
    async def _process_single_transcript_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
        cache_service: Optional[Any] = None  # CacheService type, but avoid circular import
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str]]:
        """
        Process a single transcript request.

        This method handles all the logic for processing one transcript request:
        - Parameter extraction and validation
        - Video ID extraction
        - Transcript fetching with different IPs on retry
        - Content sanitization
        - Result formatting

        Args:
            req: Request dictionary with url and optional parameters
            request_id: The id of this request (for matching in response)
            secrets_manager: SecretsManager instance
            cache_service: Optional cache service for content sanitization

        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
            - request_id: The id of the request (for grouping in response)
            - results_list: List containing single transcript result (empty if error)
            - error_string_or_none: Error message if processing failed, None if successful
        """
        video_url = req.get("url", "")
        if not video_url:
            return (request_id, [], f"Missing 'url' parameter")
        
        # Sanitize URL by removing fragment parameters (#{text}) as a security measure
        # Fragments can contain malicious content and are not needed for video transcript fetching
        sanitized_url = sanitize_url_remove_fragment(video_url)
        if not sanitized_url:
            return (request_id, [], f"Invalid URL: '{video_url}' - could not sanitize")
        
        # Log if fragment was removed (for debugging)
        if '#' in video_url and '#' not in sanitized_url:
            logger.debug(f"[{request_id}] Removed fragment from URL: '{video_url}' -> '{sanitized_url}'")
        
        # Use sanitized URL for processing
        video_url = sanitized_url
        
        # Extract optional languages parameter
        languages = req.get("languages")
        
        logger.debug(f"Executing transcript fetch (id: {request_id}): url='{video_url}'")
        
        try:
            # Extract video ID from URL
            video_id = self._extract_video_id(video_url)
            if not video_id:
                return (request_id, [], f"Invalid YouTube URL: '{video_url}' - could not extract video ID")
            
            # Fetch transcript with retry logic using different IPs
            result = await self._fetch_transcript(
                video_id=video_id,
                url=video_url,
                secrets_manager=secrets_manager,
                languages=languages
            )
            
            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                return (request_id, [], f"Video {video_id}: {error_msg}")
            
            # Sanitize transcript content if present
            transcript_text = result.get("transcript", "")
            if transcript_text:
                try:
                    sanitized_transcript = await sanitize_external_content(
                        content=transcript_text,
                        content_type="text",
                        task_id=f"transcript_{request_id}_{video_id}",
                        secrets_manager=secrets_manager,
                        cache_service=cache_service
                    )
                    
                    # Check if sanitization failed or was blocked
                    if sanitized_transcript is None:
                        error_msg = f"Content sanitization failed for video {video_id}: sanitization returned None."
                        logger.error(error_msg)
                        return (request_id, [], f"Video {video_id}: Content sanitization failed - LLM call failed")
                    
                    if not sanitized_transcript or not sanitized_transcript.strip():
                        error_msg = f"Content sanitization blocked for video {video_id}: sanitization returned empty."
                        logger.error(error_msg)
                        return (request_id, [], f"Video {video_id}: Content sanitization blocked - high prompt injection risk detected")
                    
                    # Update result with sanitized transcript
                    result["transcript"] = sanitized_transcript
                    
                except Exception as e:
                    error_msg = f"Error sanitizing transcript for video {video_id}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    return (request_id, [], f"Video {video_id}: Error sanitizing transcript - {str(e)}")
            
            # Build result in expected format
            transcript_result = {
                "type": "transcript_result",
                "url": video_url,
                "transcript": result.get("transcript"),
                "word_count": result.get("word_count"),
                "characters_count": result.get("characters_count"),
                "language": result.get("language"),
                "hash": self._generate_result_hash(video_url)
            }
            
            logger.info(f"Transcript fetch (id: {request_id}) completed: video_id='{video_id}'")
            
            # Create creator income entry asynchronously (fire-and-forget)
            # This doesn't block the skill response
            try:
                asyncio.create_task(
                    self._create_creator_income_for_video(
                        video_id=video_id,
                        video_url=video_url,
                        app_id=self.app_id,
                        skill_id=self.skill_id,
                        secrets_manager=secrets_manager
                    )
                )
            except Exception as e:
                # Log but don't fail - income tracking failure shouldn't break skill execution
                logger.warning(f"Failed to create creator income entry for video '{video_id}': {e}")
            
            return (request_id, [transcript_result], None)
            
        except Exception as e:
            error_msg = f"URL '{video_url}' (id: {request_id}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)
    
    async def _create_creator_income_for_video(
        self,
        video_id: str,
        video_url: str,
        app_id: str,
        skill_id: str,
        secrets_manager: SecretsManager
    ) -> None:
        """
        Create creator income entry for a YouTube video.
        
        This method is called asynchronously (fire-and-forget) after successful transcript fetch.
        It fetches the channel ID from video metadata, then creates a creator_income entry
        with 10 credits reserved for the creator (50% of 20 credits total).
        
        Args:
            video_id: The YouTube video ID
            video_url: The original video URL
            app_id: The app ID (e.g., 'videos')
            skill_id: The skill ID (e.g., 'get_transcript')
            secrets_manager: SecretsManager instance for YouTube API access
        """
        try:
            # Fetch video metadata to get channel ID
            # This uses the YouTube Data API which costs 1 quota unit per batch
            try:
                video_metadata = await get_video_metadata_batched(
                    video_ids=[video_id],
                    secrets_manager=secrets_manager,
                    batch_size=1
                )
                
                video_data = video_metadata.get(video_id)
                if not video_data:
                    logger.warning(f"Video metadata not found for video_id '{video_id}', skipping creator income creation")
                    return
                
                snippet = video_data.get('snippet', {})
                channel_id = snippet.get('channelId')
                
                if not channel_id:
                    logger.warning(f"Channel ID not found in video metadata for video_id '{video_id}', skipping creator income creation")
                    return
                    
            except ValueError as e:
                # YouTube API key not available
                logger.debug(f"YouTube API key not available for channel ID lookup: {e}. Skipping creator income creation.")
                return
            except Exception as e:
                logger.warning(f"Error fetching video metadata for channel ID: {e}. Skipping creator income creation.")
                return
            
            # Create services for creator revenue service
            # These are created fresh for each async task (fire-and-forget)
            cache_service = CacheService()
            encryption_service = EncryptionService(cache_service=cache_service)
            directus_service = DirectusService(
                cache_service=cache_service,
                encryption_service=encryption_service
            )
            
            revenue_service = CreatorRevenueService(
                directus_service=directus_service,
                encryption_service=encryption_service
            )
            
            # Revenue split: 10 credits to creator, 10 to OpenMates (50/50 split)
            # Total cost is 20 credits per request
            creator_credits = 10
            
            # Create income entry
            # Use video_id as content_id (already extracted and normalized)
            success = await revenue_service.create_income_entry(
                owner_id=channel_id,
                content_id=video_id,
                content_type="video",
                app_id=app_id,
                skill_id=skill_id,
                credits=creator_credits,
                income_source="skill_usage"
            )
            
            if success:
                logger.debug(f"Created creator income entry for video: channel_id={channel_id}, video_id={video_id}, credits={creator_credits}")
            else:
                logger.warning(f"Failed to create creator income entry for video: channel_id={channel_id}, video_id={video_id}")
                
        except Exception as e:
            # Log but don't raise - income tracking failure shouldn't break skill execution
            logger.error(f"Error creating creator income entry for video '{video_id}': {e}", exc_info=True)
    
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
        # Get or create SecretsManager using BaseSkill helper
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="TranscriptSkill",
            error_response_factory=lambda msg: TranscriptResponse(results=[], error=msg),
            logger=logger
        )
        if error_response:
            return error_response
        
        # Validate requests array - convert Pydantic models to dicts if needed
        # The requests might be TranscriptRequestItem instances (from Pydantic validation)
        # or plain dicts (from internal calls)
        requests_as_dicts = []
        for req in requests:
            if isinstance(req, TranscriptRequestItem):
                # Convert Pydantic model to dict
                requests_as_dicts.append(req.model_dump())
            elif isinstance(req, dict):
                # Already a dict, use as-is
                requests_as_dicts.append(req)
            else:
                # Try to convert to dict
                requests_as_dicts.append(dict(req))
        
        # Validate requests array using BaseSkill helper
        validated_requests, error = self._validate_requests_array(
            requests=requests_as_dicts,
            required_field="url",
            field_display_name="url",
            empty_error_message="No transcript requests provided. 'requests' array must contain at least one request with a 'url' field.",
            logger=logger
        )
        if error:
            return TranscriptResponse(results=[], error=error)
        
        # Proxy configuration is now handled per-attempt in _fetch_transcript
        # to ensure different IPs are used for each retry
        logger.debug("Proxy configurations will be built per-retry to use different IPs")
        
        # Initialize cache service for content sanitization (shared across all requests)
        from backend.core.api.app.services.cache import CacheService
        cache_service = CacheService()
        
        # Process all transcript requests in parallel using BaseSkill helper
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_transcript_request,
            logger=logger,
            secrets_manager=secrets_manager,
            cache_service=cache_service
        )
        
        # Group results by request ID using BaseSkill helper
        grouped_results, errors = self._group_results_by_request_id(
            results=results,
            requests=validated_requests,
            logger=logger
        )
        
        # Calculate success/failed counts for logging (skill-specific tracking)
        success_count = sum(1 for group in grouped_results if len(group.get("results", [])) > 0)
        failed_count = len(errors)
        
        # Build response with errors using BaseSkill helper
        response = self._build_response_with_errors(
            response_class=TranscriptResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="YouTube Transcript API",
            suggestions=getattr(self, 'suggestions_follow_up_requests', None),
            logger=logger
        )
        
        # Add skill-specific logging
        total_results = sum(len(group.get("results", [])) for group in grouped_results)
        logger.info(f"Transcript skill execution completed: {len(grouped_results)} request groups, {success_count} successful, {failed_count} failed, {total_results} total results")
        
        return response
    
    # _generate_result_hash is now provided by BaseSkill