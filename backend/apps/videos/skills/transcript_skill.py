# Published captions from the media.ccc.de public API.

import logging
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator
from celery import Celery  # For Celery type hinting

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.cache import CacheService
from backend.shared.python_utils.app_skill_helpers import sanitize_external_content
from backend.shared.python_utils.url_normalizer import sanitize_url_remove_fragment
from backend.shared.providers.media_ccc import MediaCCCClient, extract_media_ccc_slug

logger = logging.getLogger(__name__)


class TranscriptRequestItem(BaseModel):
    """One published-caption request for a canonical media.ccc.de talk URL."""
    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    url: str = Field(..., description="Canonical https://media.ccc.de/v/<slug> URL. YouTube transcripts are unavailable.")
    languages: Optional[List[str]] = Field(
        default=None,
        description="List of language codes to try for transcript (ISO 639-1, e.g., 'en', 'de', 'es', 'fr'). The API will use the first available language."
    )
    
    @field_validator('url')
    @classmethod
    def validate_video_url(cls, v: str) -> str:
        """Reject unsupported transcript sources before any provider call."""
        if not extract_media_ccc_slug(v):
            raise ValueError("Only https://media.ccc.de/v/<slug> captions are supported. YouTube transcripts are unavailable.")
        return v


class TranscriptRequest(BaseModel):
    """
    Request model for transcript skill.
    Supports multiple video URLs in a single request for parallel processing.
    """
    # Multiple video URLs (standard format per REST API architecture)
    requests: List[TranscriptRequestItem] = Field(
        ...,
        description="Array of transcript requests. Each object contains a media.ccc.de talk 'url' and optional language preferences."
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
        default="media.ccc.de",
        description="Published caption provider: media.ccc.de."
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
            "metadata"
        ],
        description="List of field paths (supports dot notation) that should be excluded from LLM inference to reduce token usage. These fields are preserved in chat history for UI rendering but filtered out before sending to LLM."
    )
    # preview_data removed: redundant metadata that can be derived from results
    # preview_data: Optional[Dict[str, Any]] = Field(
    #     None,
    #     description="Preview data for frontend rendering. This is skill-specific metadata for UI display (e.g., video_count, success_count, etc.). Does NOT include actual results - those are in 'results' field."
    # )


class TranscriptSkill(BaseSkill):
    """Fetch published media.ccc.de captions, processing requests independently."""

    def __init__(self,
                 app,  # BaseApp instance - required by BaseSkill
                 app_id: str,
                 skill_id: str,
                 skill_name: str,
                 skill_description: str,
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
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer
        )
        
        # Store skill_operational_defaults if provided
        if skill_operational_defaults:
            logger.debug(f"TranscriptSkill '{self.skill_name}' received operational_defaults: {skill_operational_defaults}")
        
        # Initialize secrets manager (will be injected in execute method)
        self.secrets_manager: Optional[SecretsManager] = None
        
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
        - Published-caption fetching
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
            return (request_id, [], "Missing 'url' parameter")
        
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
            ccc_slug = extract_media_ccc_slug(video_url)
            if ccc_slug:
                video_id = ccc_slug
                captions = await MediaCCCClient().fetch_transcript(video_url, languages)
                plain_text = " ".join(caption.text for caption in captions.captions)
                result = {
                    "success": True,
                    "transcript": self._format_transcript_with_timestamps(
                        [caption.model_dump() for caption in captions.captions]
                    ),
                    "word_count": len(plain_text.split()),
                    "characters_count": len(plain_text),
                    "language": captions.language,
                }
            else:
                return (request_id, [], "Only media.ccc.de captions are supported. YouTube transcripts are unavailable.")

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
            if ccc_slug:
                transcript_result["provider"] = "media.ccc.de"
                # Do not send externally supplied title text to inference without
                # sanitization. Metadata remains available to transcript embeds.
                transcript_result["metadata"] = {"title": captions.title}
            
            logger.debug(f"Transcript fetch completed for video {video_id}")
            
            return (request_id, [transcript_result], None)
            
        except Exception as e:
            error_msg = f"URL '{video_url}' (id: {request_id}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)
    
    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs
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
        3. I/O operations (published-caption fetching) use await
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

        provider = "media.ccc.de"
        
        validated_requests, invalid_grouped_results, validation_errors, error = self._partition_requests_by_required_fields(
            requests=requests_as_dicts,
            required_fields=["url"],
            field_display_names={"url": "url"},
            empty_error_message="No transcript requests provided. 'requests' array must contain at least one request with a 'url' field.",
            logger=logger
        )
        if error:
            return TranscriptResponse(results=[], error=error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=TranscriptResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider=provider,
                suggestions=getattr(self, 'suggestions_follow_up_requests', None),
                logger=logger
            )
        
        # Initialize cache service for content sanitization (shared across all requests)
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
            requests=requests_as_dicts,
            logger=logger
        )
        grouped_results = self._merge_grouped_results_preserving_request_order(
            grouped_results,
            invalid_grouped_results,
            requests_as_dicts,
        )
        
        # Calculate success/failed counts for logging (skill-specific tracking)
        success_count = sum(1 for group in grouped_results if len(group.get("results", [])) > 0)
        failed_count = len(errors)
        
        # Build response with errors using BaseSkill helper
        response = self._build_response_with_errors(
            response_class=TranscriptResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider=provider,
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
