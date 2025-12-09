# backend/apps/videos/skills/search_skill.py
#
# Videos search skill implementation.
# Provides video search functionality using the Brave Search API.
#
# This skill supports multiple search queries in a single request,
# processing them in parallel (up to 5 parallel requests).

import logging
import os
import json
import yaml
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting
from toon_format import encode, decode, DecodeOptions

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.brave.brave_search import search_videos
from backend.shared.providers.youtube.youtube_metadata import (
    get_video_metadata_batched,
    get_channel_thumbnails_batched,
    extract_youtube_id_from_url
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content, check_rate_limit, wait_for_rate_limit
# RateLimitScheduledException is no longer caught here - it bubbles up to route handler
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    """
    Request model for videos search skill.
    Always uses 'requests' array format for consistency and parallel processing support.
    Each request specifies its own parameters with defaults defined in the tool_schema.
    """
    # Multiple queries (standard format per REST API architecture)
    requests: List[Dict[str, Any]] = Field(
        ...,
        description="Array of search request objects. Each object must contain 'query' and can include optional parameters (count, country, search_lang, safesearch) with defaults from schema."
    )


class SearchResult(BaseModel):
    """Individual search result model."""
    title: str
    url: str
    description: str
    age: Optional[str] = None
    meta_url: Optional[Dict[str, Any]] = None
    language: Optional[str] = None
    family_friendly: Optional[bool] = True


class SearchResponse(BaseModel):
    """Response model for videos search skill."""
    # Results are grouped by request id - each entry contains 'id' and 'results' array
    # This structure allows clients to match responses to original requests without redundant data
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' (matching request id) and 'results' array with actual video search results for that request."
    )
    provider: str = Field(
        default="Brave Search",
        description="The search provider used (e.g., 'Brave Search')"
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on search results"
    )
    error: Optional[str] = Field(None, description="Error message if search failed")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "meta_url.profile_image",
            "thumbnail.original"
        ],
        description="List of field paths (supports dot notation) that should be excluded from LLM inference to reduce token usage. These fields are preserved in chat history for UI rendering but filtered out before sending to LLM."
    )
    # preview_data removed: redundant metadata that can be derived from results and input
    # preview_data: Optional[Dict[str, Any]] = Field(
    #     None,
    #     description="Preview data for frontend rendering. This is skill-specific metadata for UI display (e.g., query, result_count, etc.). Does NOT include actual results - those are in 'results' field."
    # )


class SearchSkill(BaseSkill):
    """
    Videos search skill that uses Brave Search API to search for videos.
    
    Supports multiple search queries in a single request, processing them in parallel.
    Each query is executed independently and results are combined.
    
    ARCHITECTURE DECISION: Direct Async Execution vs Celery Tasks
    ==============================================================
    
    This skill executes directly in the FastAPI route handler (app-videos container) using
    async/await, rather than dispatching to a Celery task in app-videos-worker. This is an
    intentional architectural decision for the following reasons:
    
    1. **Performance & Latency**
       - Video search is a quick operation (typically 0.5-2 seconds)
       - Direct async execution has ~0ms overhead vs Celery's ~50-200ms overhead
         (task dispatch + queue wait + result retrieval)
       - Users expect immediate results for search queries
    
    2. **Non-Blocking Concurrency**
       - The execute() method uses async/await, making it non-blocking
       - FastAPI's event loop can handle thousands of concurrent requests efficiently
       - During I/O operations (HTTP calls to Brave API, content sanitization), the
         event loop yields control, allowing other requests to be processed
       - This is NOT blocking - multiple requests are processed concurrently
    
    3. **I/O-Bound Nature**
       - Video search is primarily I/O-bound (network calls, not CPU-intensive)
       - Async I/O is perfectly suited for this use case
       - No CPU-bound work that would benefit from separate worker processes
    
    4. **Simplicity**
       - Direct execution is simpler: no task queue, no polling, no result storage
       - Easier to debug and monitor (logs appear directly in app-videos)
       - Fewer moving parts = fewer failure points
    
    When to Use Celery Instead:
    ---------------------------
    Celery tasks are appropriate for:
    - Long-running operations (>5 seconds)
    - CPU-intensive work that would block the event loop
    - Operations requiring retry mechanisms and task queuing
    - Operations that need to be processed in background (fire-and-forget)
    - Operations requiring independent worker scaling
    
    Examples of skills that SHOULD use Celery:
    - AI chat processing (long-running, complex)
    - Image generation (CPU-intensive, long-running)
    - Large data processing tasks
    
    Examples of skills that should use direct async (like this one):
    - Video search (quick, I/O-bound)
    - Quick API lookups
    - Simple data transformations
    - Fast external service calls
    
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
                 skill_name: str,  # Changed from 'name' to match BaseSkill
                 skill_description: str,  # Changed from 'description' to match BaseSkill
                 stage: str = "development",
                 full_model_reference: Optional[str] = None,  # From skill's app.yml definition
                 pricing_config: Optional[Dict[str, Any]] = None,  # From skill's app.yml definition
                 celery_producer: Optional[Celery] = None,  # Added to match BaseSkill
                 # This is for SearchSkill's specific operational defaults from its 'default_config' block in app.yml
                 skill_operational_defaults: Optional[Dict[str, Any]] = None
                 ):
        """
        Initialize SearchSkill.
        
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
        # Call BaseSkill constructor with all required parameters (excluding skill_operational_defaults)
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
        
        # Store skill_operational_defaults if provided (for future use if needed)
        # Currently SearchSkill doesn't use operational defaults, but we accept it for consistency
        if skill_operational_defaults:
            logger.debug(f"SearchSkill '{self.skill_name}' received operational_defaults: {skill_operational_defaults}")
            # Future: Parse and use skill_operational_defaults if SearchSkill needs specific config
        
        # Load follow-up suggestions from app.yml
        # The app.yml file is located in the same directory as this skill's parent app
        self.suggestions_follow_up_requests: List[str] = []
        self._load_suggestions_from_app_yml()
        
        self.secrets_manager: Optional[SecretsManager] = None
    
    def _load_suggestions_from_app_yml(self) -> None:
        """
        Load follow-up suggestions from app.yml file.
        
        The suggestions are defined in app.yml under:
        skills[].suggestions_follow_up_requests
        
        If the suggestions cannot be loaded from YAML, the list will remain empty.
        """
        try:
            # Get the app directory (parent of skills directory)
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            app_dir = os.path.dirname(current_file_dir)  # Go up from skills/ to app/
            app_yml_path = os.path.join(app_dir, "app.yml")
            
            if not os.path.exists(app_yml_path):
                logger.error(f"app.yml not found at {app_yml_path}, suggestions_follow_up_requests will be empty")
                self.suggestions_follow_up_requests = []
                return
            
            with open(app_yml_path, 'r', encoding='utf-8') as f:
                app_config = yaml.safe_load(f)
            
            if not app_config:
                logger.error(f"app.yml is empty at {app_yml_path}, suggestions_follow_up_requests will be empty")
                self.suggestions_follow_up_requests = []
                return
            
            # Find the search skill in the skills list
            skills = app_config.get("skills", [])
            for skill in skills:
                if skill.get("id", "").strip() == "search":
                    suggestions = skill.get("suggestions_follow_up_requests", [])
                    if suggestions and isinstance(suggestions, list):
                        self.suggestions_follow_up_requests = [str(s) for s in suggestions]
                        logger.debug(f"Loaded {len(self.suggestions_follow_up_requests)} follow-up suggestions from app.yml")
                        return
                    else:
                        logger.warning(f"Follow-up suggestions not found or invalid in app.yml for search skill, suggestions_follow_up_requests will be empty")
                        self.suggestions_follow_up_requests = []
                        return
            
            # If search skill not found
            logger.error(f"Search skill not found in app.yml, suggestions_follow_up_requests will be empty")
            self.suggestions_follow_up_requests = []
            
        except Exception as e:
            logger.error(f"Error loading follow-up suggestions from app.yml: {e}", exc_info=True)
            self.suggestions_follow_up_requests = []
    
    async def _process_single_search_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
        cache_service: CacheService
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str]]:
        """
        Process a single video search request.
        
        This method handles all the logic for processing one video search request:
        - Parameter extraction and validation
        - Rate limit checking
        - API call to Brave Videos Search
        - Content sanitization
        - Result formatting
        
        Args:
            req: Request dictionary with query and optional parameters
            request_id: The id of this request (for matching in response)
            secrets_manager: SecretsManager instance
            cache_service: CacheService instance for rate limiting
        
        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
            - request_id: The id of the request (for grouping in response)
            - results_list: List of video search result previews (empty if error)
            - error_string_or_none: Error message if processing failed, None if successful
        """
        # Extract query and parameters from request
        search_query = req.get("query") or req.get("q")
        if not search_query:
            return (request_id, [], f"Missing 'query' parameter")
        
        # Extract request-specific parameters (with defaults from schema)
        req_count = req.get("count", 10)  # Default from schema
        # Enforce maximum of 20 results to limit sanitization costs
        if req_count and req_count > 20:
            logger.warning(f"Requested count {req_count} exceeds maximum of 20 for video search '{search_query}' (id: {request_id}). Capping to 20.")
            req_count = 20
        req_country_raw = req.get("country", "us")  # Default from schema
        req_lang = req.get("search_lang", "en")  # Default from schema
        req_safesearch = req.get("safesearch", "moderate")  # Default from schema
        
        # CRITICAL: Validate and correct country code to ensure it's valid for Brave Search API
        VALID_BRAVE_COUNTRY_CODES = {
            "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "GR", "HK", 
            "IN", "ID", "IT", "JP", "KR", "MY", "MX", "NL", "NZ", "NO", "CN", "PL", "PT", 
            "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW", "TR", "GB", "US", "ALL"
        }
        req_country_upper = req_country_raw.upper() if req_country_raw else "US"
        if req_country_upper not in VALID_BRAVE_COUNTRY_CODES:
            logger.warning(
                f"Invalid country code '{req_country_raw}' for video search '{search_query}' (id: {request_id}). "
                f"Valid codes: {sorted(VALID_BRAVE_COUNTRY_CODES)}. Falling back to 'us'."
            )
            req_country = "us"
        else:
            req_country = req_country_upper
        
        logger.debug(f"Executing video search (id: {request_id}): query='{search_query}', country='{req_country}'")
        
        try:
            # Check and enforce rate limits before calling external API
            provider_id = "brave"  # Brave Search provider
            skill_id = "search"
            
            # Check rate limit
            is_allowed, retry_after = await check_rate_limit(
                provider_id=provider_id,
                skill_id=skill_id,
                cache_service=cache_service
            )
            
            # If rate limited, wait for the limit to reset
            if not is_allowed:
                logger.info(f"Rate limit hit for video search '{search_query}' (id: {request_id}), waiting for reset...")
                try:
                    celery_producer = None
                    celery_task_context = None
                    if hasattr(self.app, 'celery_producer') and self.app.celery_producer:
                        celery_producer = self.app.celery_producer
                        celery_task_context = {
                            "app_id": self.app_id,
                            "skill_id": self.skill_id,
                            "arguments": {
                                "query": search_query,
                                "count": req_count,
                                "country": req_country,
                                "search_lang": req_lang,
                                "safesearch": req_safesearch
                            },
                            # Include chat context for followup message generation
                            "chat_id": self._current_chat_id,
                            "message_id": self._current_message_id
                        }
                    
                    # Wait for rate limit - if rate limit requires long wait, this will raise
                    # RateLimitScheduledException which should bubble up to route handler
                    await wait_for_rate_limit(
                        provider_id=provider_id,
                        skill_id=skill_id,
                        cache_service=cache_service,
                        celery_producer=celery_producer,
                        celery_task_context=celery_task_context
                    )
                except Exception as e:
                    # Re-raise exceptions from wait_for_rate_limit (e.g., RateLimitScheduledException)
                    # These should bubble up to the route handler
                    raise
            
            # Call Brave Videos Search API - always search for 50 videos to get best selection
            # We'll filter and sort by view count, then return top 10
            brave_search_count = 50
            search_result = await search_videos(
                query=search_query,
                secrets_manager=secrets_manager,
                count=brave_search_count,
                country=req_country,
                search_lang=req_lang,
                safesearch=req_safesearch,
                sanitize_output=True
            )
            
            if search_result.get("error"):
                return (request_id, [], f"Query '{search_query}': {search_result['error']}")
            
            # Check if sanitization should be skipped
            should_sanitize = search_result.get("sanitize_output", True)
            
            # Get Brave Search results
            brave_results = search_result.get("results", [])
            
            # Extract YouTube video IDs from Brave Search results
            youtube_videos = []  # List of (video_id, brave_result) tuples
            for result in brave_results:
                url = result.get("url", "")
                video_id = extract_youtube_id_from_url(url)
                if video_id:
                    youtube_videos.append((video_id, result))
            
            if not youtube_videos:
                logger.warning(f"No YouTube videos found in Brave Search results for query '{search_query}' (id: {request_id})")
                return (request_id, [], f"Query '{search_query}': No YouTube videos found in search results")
            
            logger.debug(f"Found {len(youtube_videos)} YouTube videos out of {len(brave_results)} total results")
            
            # Get YouTube metadata for all videos (batched)
            video_ids = [vid for vid, _ in youtube_videos]
            try:
                youtube_metadata = await get_video_metadata_batched(
                    video_ids=video_ids,
                    secrets_manager=secrets_manager,
                    batch_size=50
                )
            except ValueError as e:
                # YouTube API key not available - fall back to Brave Search results only
                logger.warning(f"YouTube API not available: {e}. Using Brave Search results without view count sorting.")
                youtube_metadata = {}
            except Exception as e:
                logger.error(f"Error fetching YouTube metadata: {e}", exc_info=True)
                # Continue with Brave Search results only
                youtube_metadata = {}
            
            # Extract channel IDs and fetch channel thumbnails (profile images)
            channel_ids = []
            for video_id, _ in youtube_videos:
                yt_metadata = youtube_metadata.get(video_id, {})
                snippet = yt_metadata.get('snippet', {})
                channel_id = snippet.get('channelId')
                if channel_id:
                    channel_ids.append(channel_id)
            
            # Fetch channel thumbnails (batched, 1 quota unit per batch of up to 50 channels)
            channel_thumbnails = {}
            if channel_ids:
                try:
                    channel_data = await get_channel_thumbnails_batched(
                        channel_ids=channel_ids,
                        secrets_manager=secrets_manager,
                        batch_size=50
                    )
                    # Extract thumbnails from channel data
                    for channel_id, channel_info in channel_data.items():
                        snippet = channel_info.get('snippet', {})
                        thumbnails = snippet.get('thumbnails', {})
                        # Prefer high quality, fallback to medium, then default
                        channel_thumbnails[channel_id] = (
                            thumbnails.get('high', {}).get('url') or
                            thumbnails.get('medium', {}).get('url') or
                            thumbnails.get('default', {}).get('url') or
                            None
                        )
                except Exception as e:
                    logger.warning(f"Error fetching channel thumbnails: {e}. Continuing without channel profile images.")
            
            # Extract view counts and create enriched results
            enriched_videos = []
            for video_id, brave_result in youtube_videos:
                yt_metadata = youtube_metadata.get(video_id, {})
                
                # Get view count for sorting (default to 0 if not available)
                statistics = yt_metadata.get('statistics', {})
                view_count = int(statistics.get('viewCount', 0)) if statistics else 0
                
                enriched_videos.append({
                    'video_id': video_id,
                    'brave_result': brave_result,
                    'youtube_metadata': yt_metadata,
                    'view_count': view_count
                })
            
            # Sort by view count (highest first)
            enriched_videos.sort(key=lambda x: x['view_count'], reverse=True)
            
            # Take top req_count videos (default 10) after sorting by view count
            # We always search for 50 videos from Brave, but return only req_count after sorting
            result_count = req_count if req_count else 10
            top_videos = enriched_videos[:result_count]
            
            logger.info(f"Selected top {len(top_videos)} videos by view count from {len(enriched_videos)} YouTube videos (requested: {result_count})")
            
            # Convert to results format using YouTube API data where available
            results = []
            for enriched in top_videos:
                yt_metadata = enriched['youtube_metadata']
                brave_result = enriched['brave_result']
                
                # Use YouTube API data if available, otherwise fall back to Brave Search data
                if yt_metadata:
                    snippet = yt_metadata.get('snippet', {})
                    statistics = yt_metadata.get('statistics', {})
                    content_details = yt_metadata.get('contentDetails', {})
                    
                    # Extract first 30 tags
                    tags = snippet.get('tags', [])[:30] if snippet.get('tags') else []
                    
                    # Get channel ID and profile image
                    channel_id = snippet.get('channelId', '')
                    channel_profile_image = channel_thumbnails.get(channel_id) if channel_id else None
                    
                    # Build result with YouTube API data
                    # Remove favicon from meta_url, add channel profile image instead
                    meta_url = {}
                    if channel_profile_image:
                        meta_url['profile_image'] = channel_profile_image
                    
                    result = {
                        'title': snippet.get('title', brave_result.get('title', '')),
                        'url': brave_result.get('url', ''),
                        'description': snippet.get('description', brave_result.get('description', '')),
                        'age': brave_result.get('age', ''),
                        'meta_url': meta_url if meta_url else None,
                        'thumbnail': {
                            'original': snippet.get('thumbnails', {}).get('high', {}).get('url') or 
                                       snippet.get('thumbnails', {}).get('medium', {}).get('url') or
                                       brave_result.get('thumbnail', {}).get('original', '')
                        } if snippet.get('thumbnails') else brave_result.get('thumbnail'),
                        # YouTube API metadata fields
                        'viewCount': int(statistics.get('viewCount', 0)) if statistics.get('viewCount') else 0,
                        'likeCount': int(statistics.get('likeCount', 0)) if statistics.get('likeCount') else 0,
                        'commentCount': int(statistics.get('commentCount', 0)) if statistics.get('commentCount') else 0,
                        'tags': tags,
                        'channelTitle': snippet.get('channelTitle', ''),
                        'publishedAt': snippet.get('publishedAt', ''),
                        'duration': content_details.get('duration', '') if content_details else ''
                    }
                else:
                    # Fall back to Brave Search data only
                    result = {
                        'title': brave_result.get('title', ''),
                        'url': brave_result.get('url', ''),
                        'description': brave_result.get('description', ''),
                        'age': brave_result.get('age', ''),
                        'meta_url': brave_result.get('meta_url'),
                        'thumbnail': brave_result.get('thumbnail'),
                        'viewCount': 0,
                        'likeCount': 0,
                        'commentCount': 0,
                        'tags': [],
                        'channelTitle': '',
                        'publishedAt': '',
                        'duration': ''
                    }
                
                results.append(result)
            task_id = f"video_search_{request_id}_{search_query[:50]}"
            
            # Build JSON structure with only text fields that need sanitization
            # Include title, description, and tags from YouTube API
            text_data_for_sanitization = {"results": []}
            result_metadata = []
            
            for idx, result in enumerate(results):
                title = result.get("title", "").strip()
                description = result.get("description", "").strip()
                tags = result.get("tags", [])
                
                text_data_for_sanitization["results"].append({
                    "title": title,
                    "description": description,
                    "tags": tags
                })
                
                # Store non-text metadata (including YouTube API statistics)
                meta_url = result.get("meta_url", {})
                profile_image = None
                if isinstance(meta_url, dict):
                    profile_image = meta_url.get("profile_image")
                
                thumbnail = result.get("thumbnail", {})
                thumbnail_original = None
                if isinstance(thumbnail, dict):
                    thumbnail_original = thumbnail.get("original")
                
                result_metadata.append({
                    "url": result.get("url", ""),
                    "age": result.get("age", ""),
                    "profile_image": profile_image,
                    "thumbnail_original": thumbnail_original,
                    "original_title": title,
                    "original_description": description,
                    "original_tags": tags,
                    # YouTube API metadata
                    "viewCount": result.get("viewCount", 0),
                    "likeCount": result.get("likeCount", 0),
                    "commentCount": result.get("commentCount", 0),
                    "channelTitle": result.get("channelTitle", ""),
                    "publishedAt": result.get("publishedAt", ""),
                    "duration": result.get("duration", "")
                })
            
            previews: List[Dict[str, Any]] = []
            
            # Skip sanitization if sanitize_output=False
            if not should_sanitize:
                logger.debug(f"[{task_id}] Sanitization skipped (sanitize_output=False), using raw results")
                for idx, result in enumerate(results):
                    # Ensure meta_url only contains profile_image, not favicon
                    meta_url = result.get("meta_url", {})
                    meta_url_dict = {}
                    if isinstance(meta_url, dict) and meta_url.get("profile_image"):
                        meta_url_dict["profile_image"] = meta_url["profile_image"]
                    
                    preview = {
                        "type": "video_result",
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "description": result.get("description", ""),
                        "age": result.get("age", ""),
                        "meta_url": meta_url_dict if meta_url_dict else None,
                        "thumbnail": result.get("thumbnail"),
                        "hash": self._generate_result_hash(result.get("url", "")),
                        # YouTube API metadata fields
                        "viewCount": result.get("viewCount", 0),
                        "likeCount": result.get("likeCount", 0),
                        "commentCount": result.get("commentCount", 0),
                        "tags": result.get("tags", [])[:30],  # First 30 tags
                        "channelTitle": result.get("channelTitle", ""),
                        "publishedAt": result.get("publishedAt", ""),
                        "duration": result.get("duration", "")
                    }
                    previews.append(preview)
            else:
                # Convert JSON to TOON format and sanitize
                if text_data_for_sanitization["results"]:
                    try:
                        toon_data_for_encoding = {"results": []}
                        for result in text_data_for_sanitization["results"]:
                            toon_data_for_encoding["results"].append({
                                "title": result.get("title", ""),
                                "description": result.get("description", ""),
                                "tags": result.get("tags", [])
                            })
                        
                        toon_text = encode(toon_data_for_encoding)
                        logger.info(f"[{task_id}] Batching {len(results)} video search results into single TOON-format sanitization request ({len(toon_text)} chars, ~{len(toon_text)/4:.0f} tokens)")
                        
                        # Sanitize all text content in one request
                        sanitized_toon = await sanitize_external_content(
                            content=toon_text,
                            content_type="text",
                            task_id=task_id,
                            secrets_manager=secrets_manager,
                            cache_service=cache_service
                        )
                        
                        if sanitized_toon is None:
                            error_msg = f"[{task_id}] Content sanitization failed: sanitization returned None."
                            logger.error(error_msg)
                            return (request_id, [], f"Query '{search_query}': Content sanitization failed - LLM call failed")
                        
                        if not sanitized_toon or not sanitized_toon.strip():
                            error_msg = f"[{task_id}] Content sanitization blocked: sanitization returned empty."
                            logger.error(error_msg)
                            return (request_id, [], f"Query '{search_query}': Content sanitization blocked - high prompt injection risk detected")
                        
                        # Decode sanitized TOON back to Python dict
                        sanitized_data = None
                        try:
                            try:
                                sanitized_data = decode(sanitized_toon, DecodeOptions(indent=2, strict=True))
                            except (ValueError, Exception) as decode_error:
                                logger.warning(f"[{task_id}] Strict TOON decode failed: {decode_error}. Attempting lenient decode...")
                                sanitized_data = decode(sanitized_toon, DecodeOptions(indent=2, strict=False))
                                logger.info(f"[{task_id}] Lenient TOON decode succeeded.")
                            
                            if not isinstance(sanitized_data, dict) or "results" not in sanitized_data:
                                raise ValueError("Invalid sanitized TOON structure")
                            
                            sanitized_results = sanitized_data.get("results", [])
                            if not all(isinstance(r, dict) for r in sanitized_results):
                                raise ValueError("Sanitized results contain non-dict items")
                                
                        except Exception as e:
                            error_msg = f"[{task_id}] Failed to decode sanitized TOON: {e}"
                            logger.error(error_msg, exc_info=True)
                            return (request_id, [], f"Query '{search_query}': Failed to decode sanitized TOON content - {str(e)}")
                        
                        # Map sanitized content back to results
                        sanitized_results = sanitized_data.get("results", [])
                        
                        for idx, metadata in enumerate(result_metadata):
                            sanitized_result = sanitized_results[idx] if idx < len(sanitized_results) else None
                            
                            if not isinstance(sanitized_result, dict):
                                continue
                            
                            sanitized_title = sanitized_result.get("title", "").strip() if isinstance(sanitized_result.get("title"), str) else ""
                            sanitized_description = sanitized_result.get("description", "").strip() if isinstance(sanitized_result.get("description"), str) else ""
                            sanitized_tags = sanitized_result.get("tags", []) if isinstance(sanitized_result.get("tags"), list) else []
                            
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Video search result {idx} title empty after sanitization, using original")
                                sanitized_title = metadata["original_title"]
                            
                            if not sanitized_description or not sanitized_description.strip():
                                sanitized_description = metadata["original_description"]
                            
                            if not sanitized_tags:
                                sanitized_tags = metadata["original_tags"]
                            
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Video search result {idx} title blocked due to prompt injection risk")
                                continue
                            
                            # Build preview with sanitized content and YouTube API metadata
                            meta_url_dict = {}
                            if metadata.get("profile_image"):
                                meta_url_dict["profile_image"] = metadata["profile_image"]
                            
                            preview = {
                                "type": "video_result",
                                "title": sanitized_title,
                                "url": metadata["url"],
                                "description": sanitized_description,
                                "age": metadata["age"],
                                "meta_url": meta_url_dict if meta_url_dict else None,
                                "thumbnail": {"original": metadata["thumbnail_original"]} if metadata["thumbnail_original"] else None,
                                "hash": self._generate_result_hash(metadata["url"]),
                                # YouTube API metadata fields
                                "viewCount": metadata.get("viewCount", 0),
                                "likeCount": metadata.get("likeCount", 0),
                                "commentCount": metadata.get("commentCount", 0),
                                "tags": sanitized_tags[:30],  # First 30 tags
                                "channelTitle": metadata.get("channelTitle", ""),
                                "publishedAt": metadata.get("publishedAt", ""),
                                "duration": metadata.get("duration", "")
                            }
                            previews.append(preview)
                    
                    except Exception as e:
                        error_msg = f"[{task_id}] Error encoding/decoding TOON format: {e}"
                        logger.error(error_msg, exc_info=True)
                        return (request_id, [], f"Query '{search_query}': TOON encoding/decoding error - {str(e)}")
                else:
                    logger.warning(f"[{task_id}] No text content found in video search results to sanitize")
                    for idx, result in enumerate(results):
                        meta_url = result.get("meta_url", {})
                        profile_image = meta_url.get("profile_image") if isinstance(meta_url, dict) else None
                        thumbnail = result.get("thumbnail", {})
                        thumbnail_original = thumbnail.get("original") if isinstance(thumbnail, dict) else None
                        
                        meta_url_dict = {}
                        if profile_image:
                            meta_url_dict["profile_image"] = profile_image
                        
                        preview = {
                            "type": "video_result",
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "description": result.get("description", ""),
                            "age": result.get("age", ""),
                            "meta_url": meta_url_dict if meta_url_dict else None,
                            "thumbnail": {"original": thumbnail_original} if thumbnail_original else None,
                            "hash": self._generate_result_hash(result.get("url", "")),
                            # YouTube API metadata fields
                            "viewCount": result.get("viewCount", 0),
                            "likeCount": result.get("likeCount", 0),
                            "commentCount": result.get("commentCount", 0),
                            "tags": result.get("tags", [])[:30],  # First 30 tags
                            "channelTitle": result.get("channelTitle", ""),
                            "publishedAt": result.get("publishedAt", ""),
                            "duration": result.get("duration", "")
                        }
                        previews.append(preview)
            
            logger.info(f"Video search (id: {request_id}) completed: {len(previews)} results for '{search_query}'")
            return (request_id, previews, None)
            
        except Exception as e:
            error_msg = f"Query '{search_query}' (id: {request_id}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)
    
    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None
    ) -> SearchResponse:
        """
        Execute videos search skill.
        
        Always uses 'requests' array format for consistency and parallel processing support.
        Each request in the array specifies its own parameters with defaults defined in the schema.
        
        NOTE: This method executes directly in the FastAPI route handler (not via Celery).
        This is intentional - see class docstring for architecture decision rationale.
        The async/await pattern ensures non-blocking execution and excellent concurrency.
        
        Args:
            requests: Array of search request objects. Each object must contain 'query' and can include optional parameters (count, country, search_lang, safesearch).
            secrets_manager: SecretsManager instance (injected by app)
        
        Returns:
            SearchResponse with previews and optional follow-up suggestions
        
        Execution Flow:
        --------------
        1. Request received in FastAPI route handler (app-videos container)
        2. This async method is called directly (no Celery dispatch)
        3. I/O operations (Brave API calls, content sanitization) use await
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
            skill_name="SearchSkill",
            error_response_factory=lambda msg: SearchResponse(results=[], error=msg),
            logger=logger
        )
        if error_response:
            return error_response
        
        # Validate requests array using BaseSkill helper
        validated_requests, error = self._validate_requests_array(
            requests=requests,
            required_field="query",
            field_display_name="query",
            empty_error_message="No search requests provided. 'requests' array must contain at least one request with a 'query' field.",
            logger=logger
        )
        if error:
            return SearchResponse(results=[], error=error)
        
        # Initialize cache service for rate limiting (shared across all requests)
        cache_service = CacheService()
        
        # Process all search requests in parallel using BaseSkill helper
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_search_request,
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
        
        # Build response with errors using BaseSkill helper
        response = self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Brave Search",
            suggestions=self.suggestions_follow_up_requests,
            logger=logger
        )
        
        return response
    
    # _generate_result_hash is now provided by BaseSkill
