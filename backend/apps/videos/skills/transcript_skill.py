# backend/apps/videos/skills/transcript_skill.py
#
# YouTube transcript skill implementation.
# Provides functionality to fetch YouTube video transcripts via Webshare proxy.
#
# This skill:
# 1. Extracts video ID from YouTube URL
# 2. Fetches transcript using youtube-transcript-api through Webshare proxy
# 3. Returns transcript text for LLM processing

import logging
import asyncio
import random
import time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs
from pydantic import BaseModel, Field, field_validator, ValidationError
from celery import Celery  # For Celery type hinting
from requests import Session

# User-Agent generation library for realistic browser fingerprints
try:
    from user_agents import UserAgent
    USER_AGENTS_AVAILABLE = True
except ImportError:
    USER_AGENTS_AVAILABLE = False

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
    try:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        WEBSHARE_AVAILABLE = True
    except ImportError:
        # WebshareProxyConfig might not be available in older versions
        WebshareProxyConfig = None  # type: ignore
        WEBSHARE_AVAILABLE = False
    # TextFormatter removed - we now extract timestamps directly from transcript items
    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False
    WEBSHARE_AVAILABLE = False
    WebshareProxyConfig = None  # type: ignore
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
    YouTube transcript skill that fetches video transcripts via Webshare proxy with anti-detection features.

    Supports multiple video URLs in a single request, processing them in parallel.
    Each video is processed independently and results are combined.

    Proxy Configuration:
    - Uses Webshare (rotating residential proxies) - configured via secrets manager
    - Automatically rotates through residential IP pool to avoid blocks

    Anti-Detection Features:
    - Dynamic User-Agent generation (uses 'user-agents' library for current browser versions)
    - Randomized HTTP headers (Accept-Language, DNT, etc.)
    - Webshare automatically rotates through residential IP pool
    - Random delays (10-100ms) between retry attempts
    - Up to 10 retry attempts with different IPs and headers per attempt
    
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
    
    async def _build_webshare_proxy_config_async(
        self,
        secrets_manager: SecretsManager,
        filter_ip_locations: Optional[List[str]] = None
    ) -> Optional[Any]:  # Returns WebshareProxyConfig if available, None otherwise
        """
        Build Webshare proxy configuration from secrets manager (async version).
        
        Webshare uses rotating residential proxies automatically to avoid IP blocks.
        
        Args:
            secrets_manager: SecretsManager instance to get Webshare credentials
            filter_ip_locations: Optional list of country codes to filter IP locations
                                 (e.g., ["us", "de"]). If None, uses all available locations.
        
        Returns:
            WebshareProxyConfig instance if credentials are available, None otherwise
        """
        # Check if WebshareProxyConfig is available
        if not WEBSHARE_AVAILABLE or WebshareProxyConfig is None:
            logger.warning("WebshareProxyConfig not available - transcript fetching may fail without proxy")
            return None
        
        try:
            # Get Webshare credentials from secrets manager
            ws_username = await secrets_manager.get_secret(
                secret_path="kv/data/providers/webshare",
                secret_key="proxy_username"
            )
            ws_password = await secrets_manager.get_secret(
                secret_path="kv/data/providers/webshare",
                secret_key="proxy_password"
            )
            
            if not ws_username or not ws_password:
                logger.warning("Webshare credentials not found - transcript fetching may fail without proxy")
                return None
            
            # Build WebshareProxyConfig
            # If filter_ip_locations is provided, use it to limit IP pool to specific countries
            config_kwargs = {
                "proxy_username": ws_username,
                "proxy_password": ws_password,
            }
            
            if filter_ip_locations:
                config_kwargs["filter_ip_locations"] = filter_ip_locations
            
            return WebshareProxyConfig(**config_kwargs)
            
        except Exception as e:
            logger.warning(f"Error building Webshare proxy config: {e}", exc_info=True)
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
    
    def _generate_random_user_agent(self) -> str:
        """
        Generate a realistic, up-to-date User-Agent to avoid fingerprinting.

        Uses the user-agents library to generate current, realistic browser User-Agents
        that automatically stay up-to-date with actual browser versions and distributions.
        Falls back to hardcoded agents if library is unavailable.

        Returns:
            Random User-Agent string
        """
        if USER_AGENTS_AVAILABLE:
            try:
                # Generate a random UserAgent that mimics real browser distribution
                # This automatically includes current browser versions and realistic OS combinations
                user_agent = UserAgent()

                # Get a random user agent - the library handles version updates automatically
                ua_string = user_agent.random

                logger.debug(f"Generated dynamic User-Agent: {ua_string[:50]}...")
                return ua_string

            except Exception as e:
                logger.warning(f"Failed to generate dynamic User-Agent: {e}. Falling back to static list.")

        # Fallback to static list if library fails or unavailable
        user_agents = [
            # Chrome on Windows (most common)
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",

            # Chrome on macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",

            # Firefox on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",

            # Safari on macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",

            # Edge on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        ]

        return random.choice(user_agents)

    def _create_custom_http_session(self, proxy_config: Optional[object] = None) -> Session:
        """
        Create a custom HTTP session with randomized headers to avoid fingerprinting.

        This replaces the default session that youtube-transcript-api would create,
        adding randomization to help bypass YouTube's detection systems.

        Args:
            proxy_config: Optional proxy configuration to apply.
                         Can be WebshareProxyConfig (handled by YouTubeTranscriptApi) or
                         GenericProxyConfig (applied to session directly).

        Returns:
            Configured requests.Session with randomized headers
        """
        session = Session()

        # Generate randomized headers
        user_agent = self._generate_random_user_agent()
        accept_language = random.choice([
            "en-US,en;q=0.9",
            "en-US,en;q=0.8",
            "en-US,en;q=0.9,es;q=0.8",
            "en-GB,en;q=0.9",
            "en-US,en;q=0.9,de;q=0.8",
        ])
        dnt_value = random.choice(["1", "0"])

        # Set randomized headers
        session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": accept_language,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": dnt_value,  # Do Not Track header variation
            "Upgrade-Insecure-Requests": "1",
            "Connection": "close",  # Force connection close to prevent reuse and ensure IP rotation
        })

        # Apply proxy configuration if provided
        # Note: WebshareProxyConfig is handled by YouTubeTranscriptApi internally,
        # so we don't need to apply it to the session here
        # The session is only used for custom headers (User-Agent, Accept-Language, etc.)
        # Connection: close ensures each request gets a fresh connection, helping with IP rotation

        # Session details logged at trace level if needed (too verbose for debug)

        return session

    def _get_current_ip_address(self, session: Session) -> str:
        """
        Get the current IP address being used by the session.

        This helps debug whether proxy IP rotation is working correctly.

        Args:
            session: The requests session to check

        Returns:
            IP address string or error message
        """
        try:
            # Use a simple IP check service with short timeout
            response = session.get("https://api.ipify.org?format=text", timeout=5)
            if response.status_code == 200:
                ip = response.text.strip()
                return ip
            else:
                return f"HTTP {response.status_code}"
        except Exception as e:
            return f"Error: {str(e)[:50]}"

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
        max_retries: int = 10
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
            max_retries: Maximum number of retry attempts (default: 10, each with different IP address)

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

        # Pre-build proxy config for retry attempts
        # Webshare automatically rotates IPs, but we ensure proper rotation by:
        # 1. Closing sessions after each attempt (Connection: close header)
        # 2. Creating fresh YouTubeTranscriptApi instances for each attempt
        # 3. Adding delays between attempts to avoid rate limiting
        webshare_config = await self._build_webshare_proxy_config_async(secrets_manager)
        
        if webshare_config:
            logger.debug(f"Using Webshare proxy for {max_retries} retry attempts")
            proxy_configs = [webshare_config] * max_retries
        else:
            logger.warning(f"Webshare proxy not available - attempting direct connection (may fail due to IP blocks)")
            proxy_configs = [None] * max_retries

        # Run synchronous transcript fetching in thread pool to avoid blocking
        def _fetch_sync():
            """Synchronous transcript fetching function to run in thread pool."""
            logger.debug(f"Starting transcript fetch for video {video_id}, languages: {languages}, max retries: {max_retries}")

            for attempt in range(max_retries):
                try:
                    # Add random delay between attempts (10-100ms) to avoid looking like a bot
                    if attempt > 0:  # No delay on first attempt
                        delay_ms = random.randint(10, 100)
                        logger.debug(f"Adding {delay_ms}ms delay before attempt {attempt+1}/{max_retries}")
                        time.sleep(delay_ms / 1000.0)

                    # Use pre-built proxy config for this attempt (different IP for each retry)
                    proxy_config = proxy_configs[attempt]

                    # Create custom HTTP session with randomized User-Agent and headers for each attempt
                    custom_session = self._create_custom_http_session(proxy_config)

                    # Only log attempt details on first attempt or failures (reduce verbosity)
                    if attempt == 0:
                        # Check IP only on first attempt
                        current_ip = self._get_current_ip_address(custom_session) if custom_session else "N/A"
                        logger.debug(f"Attempt 1/{max_retries} for video {video_id}, IP: {current_ip}")

                    # Create YouTubeTranscriptApi instance for this attempt
                    # IMPORTANT: When using WebshareProxyConfig, we should NOT pass http_client
                    # because WebshareProxyConfig handles the proxy internally and creates its own session.
                    # Passing a custom session can interfere with the proxy setup.
                    # For direct connections (no proxy), we use custom session for anti-detection headers.
                    if proxy_config and WEBSHARE_AVAILABLE and WebshareProxyConfig and isinstance(proxy_config, WebshareProxyConfig):
                        # WebshareProxyConfig handles proxy internally - don't pass custom session
                        # This ensures the proxy works correctly and IPs rotate properly
                        ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
                        # Note: We lose custom headers here, but Webshare's residential IPs should be enough
                        # The library will create its own session with proper proxy configuration
                    elif proxy_config:
                        # For other proxy types (if any), use custom session
                        ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=custom_session)
                    else:
                        # No proxy - use custom session for anti-detection headers
                        ytt_api = YouTubeTranscriptApi(http_client=custom_session)
                    
                    try:
                        # Fetch transcript - API will pick the first available language
                        # The fetch() method returns a TranscriptList object containing transcript items
                        # Each item has: text, start (timestamp in seconds), duration (in seconds)
                        fetched = ytt_api.fetch(video_id, languages=languages)
                    finally:
                        # Close the session if we created one (only for non-Webshare cases)
                        # WebshareProxyConfig manages its own session lifecycle
                        if not (proxy_config and WEBSHARE_AVAILABLE and WebshareProxyConfig and isinstance(proxy_config, WebshareProxyConfig)):
                            custom_session.close()
                    
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

                    # Log success (simplified)
                    logger.info(f"Transcript fetched for video {video_id} (attempt {attempt+1}/{max_retries}, language: {fetched.language}, words: {len(plain_text.split())})")

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
                    # Simplified error logging
                    error_type = type(exc).__name__
                    error_msg = str(exc)[:200]  # Truncate long error messages
                    
                    # Only log detailed errors on last attempt or for specific error types
                    if attempt == max_retries - 1 or "IpBlocked" in error_type or "RequestBlocked" in error_type:
                        logger.warning(f"Transcript fetch attempt {attempt+1}/{max_retries} failed for video {video_id}: {error_type} - {error_msg}")
                    else:
                        logger.debug(f"Transcript fetch attempt {attempt+1}/{max_retries} failed for video {video_id}: {error_type}")

                    if attempt == max_retries - 1:
                        logger.error(f"All {max_retries} attempts failed for video {video_id}: {error_type}")
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
            
            logger.debug(f"Transcript fetch completed for video {video_id}")
            
            # Create creator income entry asynchronously (fire-and-forget)
            # This doesn't block the skill response
            # Skip revenue sharing if payment is disabled (self-hosted mode)
            from backend.core.api.app.utils.server_mode import is_payment_enabled
            payment_enabled = is_payment_enabled()
            
            if payment_enabled:
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
            else:
                logger.debug(f"Payment disabled (self-hosted mode). Skipping creator income entry for video '{video_id}'")
            
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
        Create creator income entries for a YouTube video.
        
        This method is called asynchronously (fire-and-forget) after successful transcript fetch.
        It fetches the channel ID from video metadata, then creates two creator_income entries:
        1. One for the video creator (channel owner) - 9 credits
        2. One for YouTube (the platform) - 1 credit, claimable by YouTube to cover their server costs
        
        Revenue split per transcript request (20 credits total):
        - Creator: 9 credits (claimable by video channel owner)
        - YouTube: 1 credit (claimable by YouTube to cover server costs)
        - OpenMates: 10 credits (covers operational costs, not tracked as creator income)
        
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
            
            # Revenue split per transcript request (20 credits total):
            # - Creator: 9 credits (claimable by video channel owner)
            # - YouTube: 1 credit (claimable by YouTube to cover their server costs)
            # - OpenMates: 10 credits (covers operational costs, not tracked as creator income)
            creator_credits = 9
            youtube_credits = 1
            
            # Create income entry for video creator (channel owner)
            # Use video_id as content_id (already extracted and normalized)
            creator_success = await revenue_service.create_income_entry(
                owner_id=channel_id,
                content_id=video_id,
                content_type="video",
                app_id=app_id,
                skill_id=skill_id,
                credits=creator_credits,
                income_source="skill_usage"
            )
            
            if creator_success:
                logger.debug(f"Created creator income entry for video: channel_id={channel_id}, video_id={video_id}, credits={creator_credits}")
            else:
                logger.warning(f"Failed to create creator income entry for video: channel_id={channel_id}, video_id={video_id}")

            # Create income entry for YouTube (the platform)
            # These credits are claimable by YouTube to cover their server costs
            # We use "youtube" as the owner_id so YouTube can claim these credits
            youtube_success = await revenue_service.create_income_entry(
                owner_id="youtube",
                content_id=video_id,
                content_type="video",
                app_id=app_id,
                skill_id=skill_id,
                credits=youtube_credits,
                income_source="skill_usage"
            )
            
            if youtube_success:
                logger.debug(f"Created YouTube income entry for video: video_id={video_id}, credits={youtube_credits} (claimable by YouTube to cover server costs)")
            else:
                logger.warning(f"Failed to create YouTube income entry for video: video_id={video_id}")
                
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
        
        # Proxy configuration is handled in _fetch_transcript
        
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
        
        # Add skill-specific logging (simplified)
        if failed_count > 0:
            logger.info(f"Transcript skill completed: {success_count} successful, {failed_count} failed")
        else:
            logger.debug(f"Transcript skill completed: {success_count} successful")
        
        return response
    
    # _generate_result_hash is now provided by BaseSkill