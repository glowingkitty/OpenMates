# backend/apps/web/skills/search_skill.py
#
# Web search skill implementation.
# Provides web search functionality using the Brave Search API.
#
# This skill supports multiple search queries in a single request,
# processing them in parallel (up to 5 parallel requests).

import logging
import os
import json
import yaml
import re
import html
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting
from toon_format import encode, decode, DecodeOptions

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.brave.brave_search import search_web
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content, check_rate_limit, wait_for_rate_limit
# RateLimitScheduledException is no longer caught here - it bubbles up to route handler
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


def strip_html_tags(text: str) -> str:
    """
    Strip HTML tags from text to produce clean plain text.
    
    This function removes all HTML tags (like <strong>, <em>, <b>, <i>, <a>, etc.)
    and decodes HTML entities to produce clean text for storage and rendering.
    
    Benefits of server-side stripping:
    - Reduces data size (smaller encrypted payloads)
    - Simplifies client-side rendering (no HTML parsing needed)
    - Ensures consistent display across all platforms
    - Prevents potential XSS vectors
    
    Args:
        text: Text that may contain HTML tags
        
    Returns:
        Clean text with all HTML tags removed and entities decoded
    """
    if not text:
        return text
    
    # Remove all HTML tags using regex
    cleaned = re.sub(r'<[^>]*>', '', text)
    
    # Decode HTML entities (e.g., &amp; -> &, &lt; -> <, etc.)
    cleaned = html.unescape(cleaned)
    
    # Clean up extra whitespace that might result from removed tags
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


class SearchRequest(BaseModel):
    """
    Request model for web search skill.
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
    """Response model for web search skill."""
    # Results are grouped by request id - each entry contains 'id' and 'results' array
    # This structure allows clients to match responses to original requests without redundant data
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' (matching request id) and 'results' array with actual search results for that request."
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
            "meta_url.favicon",
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
    Web search skill that uses Brave Search API to search the web.
    
    Supports multiple search queries in a single request, processing them in parallel.
    Each query is executed independently and results are combined.
    
    ARCHITECTURE DECISION: Direct Async Execution vs Celery Tasks
    ==============================================================
    
    This skill executes directly in the FastAPI route handler (app-web container) using
    async/await, rather than dispatching to a Celery task in app-web-worker. This is an
    intentional architectural decision for the following reasons:
    
    1. **Performance & Latency**
       - Web search is a quick operation (typically 0.5-2 seconds)
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
       - Web search is primarily I/O-bound (network calls, not CPU-intensive)
       - Async I/O is perfectly suited for this use case
       - No CPU-bound work that would benefit from separate worker processes
    
    4. **Simplicity**
       - Direct execution is simpler: no task queue, no polling, no result storage
       - Easier to debug and monitor (logs appear directly in app-web)
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
    - Web search (quick, I/O-bound)
    - Quick API lookups
    - Simple data transformations
    - Fast external service calls
    
    Current Implementation:
    ----------------------
    - Executes in: app-web (FastAPI container)
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
                        logger.warning("Follow-up suggestions not found or invalid in app.yml for search skill, suggestions_follow_up_requests will be empty")
                        self.suggestions_follow_up_requests = []
                        return
            
            # If search skill not found
            logger.error("Search skill not found in app.yml, suggestions_follow_up_requests will be empty")
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
        Process a single search request.
        
        This method handles all the logic for processing one search request:
        - Parameter extraction and validation
        - Rate limit checking
        - API call to Brave Search
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
            - results_list: List of search result previews (empty if error)
            - error_string_or_none: Error message if processing failed, None if successful
        """
        # Extract query and parameters from request
        search_query = req.get("query") or req.get("q")
        if not search_query:
            return (request_id, [], "Missing 'query' parameter")
        
        # Extract request-specific parameters (with defaults from schema)
        req_count = req.get("count", 10)  # Default from schema
        req_country_raw = req.get("country", "us")  # Default from schema
        req_lang = req.get("search_lang", "en")  # Default from schema
        req_safesearch = req.get("safesearch", "moderate")  # Default from schema
        # Default to web articles only (excludes news, videos, discussions, etc.)
        req_result_filter = req.get("result_filter", "web")  # Default to "web" for web articles
        
        # CRITICAL: Validate and correct country code to ensure it's valid for Brave Search API
        # Valid codes: AR, AU, AT, BE, BR, CA, CL, DK, FI, FR, DE, GR, HK, IN, ID, IT, JP, KR, MY, MX, NL, NZ, NO, CN, PL, PT, PH, RU, SA, ZA, ES, SE, CH, TW, TR, GB, US, ALL
        VALID_BRAVE_COUNTRY_CODES = {
            "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "GR", "HK", 
            "IN", "ID", "IT", "JP", "KR", "MY", "MX", "NL", "NZ", "NO", "CN", "PL", "PT", 
            "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW", "TR", "GB", "US", "ALL"
        }
        req_country_upper = req_country_raw.upper() if req_country_raw else "US"
        if req_country_upper not in VALID_BRAVE_COUNTRY_CODES:
            # Invalid country code - log warning and fallback to "us"
            logger.warning(
                f"Invalid country code '{req_country_raw}' for search '{search_query}' (id: {request_id}). "
                f"Valid codes: {sorted(VALID_BRAVE_COUNTRY_CODES)}. Falling back to 'us'."
            )
            req_country = "us"
        else:
            req_country = req_country_upper
        
        logger.debug(f"Executing search (id: {request_id}): query='{search_query}', country='{req_country}', result_filter='{req_result_filter}'")
        
        try:
            # Check and enforce rate limits before calling external API
            # According to app_skills.md: "Requests are never rejected due to rate limits.
            # Instead, they're queued and processed when limits allow."
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
                logger.info(f"Rate limit hit for search '{search_query}' (id: {request_id}), waiting for reset...")
                try:
                    # Try to get celery_producer from app if available
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
                except Exception:
                    # Re-raise exceptions from wait_for_rate_limit (e.g., RateLimitScheduledException)
                    # These should bubble up to the route handler
                    raise
            
            # Call Brave Search API
            # Enable extra_snippets to get additional context snippets
            # sanitize_output defaults to True for user-facing requests (sanitization required)
            search_result = await search_web(
                query=search_query,
                secrets_manager=secrets_manager,
                count=req_count,
                country=req_country,
                search_lang=req_lang,
                safesearch=req_safesearch,
                extra_snippets=True,  # Enable extra snippets for richer results
                result_filter=req_result_filter,  # Filter to web articles by default
                sanitize_output=True  # Enable sanitization for user-facing requests (default)
            )
            
            if search_result.get("error"):
                return (request_id, [], f"Query '{search_query}': {search_result['error']}")
            
            # Check if sanitization should be skipped (e.g., for health checks)
            should_sanitize = search_result.get("sanitize_output", True)  # Default to True for safety
            
            # Convert results to preview format and sanitize external content
            # Batch all text content from all results into a single sanitization request using TOON format
            results = search_result.get("results", [])
            task_id = f"search_{request_id}_{search_query[:50]}"  # Limit length for logging
            
            # Build JSON structure with only text fields that need sanitization
            # Exclude: url, page_age, profile.name, meta_url.favicon, thumbnail.original (non-text fields)
            # Include: title, description, extra_snippets (text fields for LLM inference)
            text_data_for_sanitization = {
                "results": []
            }
            result_metadata = []  # Store non-text metadata for each result
            
            for idx, result in enumerate(results):
                # Extract text fields that need sanitization
                # IMPORTANT: Strip HTML tags server-side to reduce data size and simplify client rendering
                # This removes tags like <strong>, <em>, <b>, etc. that Brave Search may include
                title = strip_html_tags(result.get("title", "").strip())
                description = strip_html_tags(result.get("description", "").strip())
                extra_snippets = result.get("extra_snippets", [])
                if not isinstance(extra_snippets, list):
                    extra_snippets = []
                # Strip HTML tags from each snippet
                extra_snippets = [strip_html_tags(snippet) for snippet in extra_snippets if snippet]
                
                # Add to text data structure for sanitization
                text_data_for_sanitization["results"].append({
                    "title": title,
                    "description": description,
                    "extra_snippets": extra_snippets
                })
                
                # Store non-text metadata (will be merged back after sanitization)
                meta_url = result.get("meta_url", {})
                favicon = None
                if isinstance(meta_url, dict):
                    favicon = meta_url.get("favicon")
                
                profile = result.get("profile", {})
                profile_name = None
                if isinstance(profile, dict):
                    profile_name = profile.get("name")
                
                thumbnail = result.get("thumbnail", {})
                thumbnail_original = None
                if isinstance(thumbnail, dict):
                    thumbnail_original = thumbnail.get("original")
                
                # DEBUG: Log thumbnail and favicon extraction
                logger.debug(
                    f"[{task_id}] Result {idx} metadata extraction: "
                    f"url={result.get('url', '')[:50]}... "
                    f"raw_thumbnail={result.get('thumbnail')}, "
                    f"raw_meta_url={result.get('meta_url')}, "
                    f"extracted_thumbnail_original={thumbnail_original}, "
                    f"extracted_favicon={favicon}"
                )
                
                result_metadata.append({
                    "url": result.get("url", ""),
                    "page_age": result.get("page_age", result.get("age", "")),
                    "profile_name": profile_name,
                    "favicon": favicon,
                    "thumbnail_original": thumbnail_original,
                    "original_title": title,
                    "original_description": description,
                    "original_extra_snippets": extra_snippets
                })
            
            previews: List[Dict[str, Any]] = []
            
            # Skip sanitization if sanitize_output=False (e.g., for health checks)
            if not should_sanitize:
                logger.debug(f"[{task_id}] Sanitization skipped (sanitize_output=False), using raw results")
                # Use raw results without sanitization but still strip HTML tags
                for idx, result in enumerate(results):
                    # Strip HTML tags even when sanitization is skipped
                    raw_extra_snippets = result.get("extra_snippets", [])
                    if not isinstance(raw_extra_snippets, list):
                        raw_extra_snippets = []
                    
                    preview = {
                        "type": "search_result",
                        "title": strip_html_tags(result.get("title", "")),
                        "url": result.get("url", ""),
                        "description": strip_html_tags(result.get("description", "")),
                        "page_age": result.get("page_age", result.get("age", "")),
                        "profile": result.get("profile"),
                        "meta_url": result.get("meta_url"),
                        "thumbnail": result.get("thumbnail"),
                        "extra_snippets": [strip_html_tags(s) for s in raw_extra_snippets if s],
                        "hash": self._generate_result_hash(result.get("url", ""))
                    }
                    previews.append(preview)
            else:
                # Convert JSON to TOON format using toon-format package
                # For proper TOON tabular format, we need uniform objects with primitive fields only
                # Convert extra_snippets list to a delimited string for tabular encoding
                if text_data_for_sanitization["results"]:
                    try:
                        # Prepare data for TOON tabular format (all fields must be primitives)
                        # Convert extra_snippets from list to pipe-delimited string for tabular format
                        toon_data_for_encoding = {
                            "results": []
                        }
                        for result in text_data_for_sanitization["results"]:
                            # Convert extra_snippets list to pipe-delimited string for tabular format
                            extra_snippets_str = "|".join(result.get("extra_snippets", [])) if isinstance(result.get("extra_snippets"), list) else ""
                            toon_data_for_encoding["results"].append({
                                "title": result.get("title", ""),
                                "description": result.get("description", ""),
                                "extra_snippets": extra_snippets_str  # String for tabular format
                            })
                        
                        # Encode to TOON format - will use tabular format for uniform objects
                        toon_text = encode(toon_data_for_encoding)
                        
                        logger.info(f"[{task_id}] Batching {len(results)} search results into single TOON-format sanitization request ({len(toon_text)} chars, ~{len(toon_text)/4:.0f} tokens)")
                        logger.debug(f"[{task_id}] TOON format data (full):\n{toon_text}")
                        
                        # Sanitize all text content in one request (preserves TOON format)
                        sanitized_toon = await sanitize_external_content(
                            content=toon_text,
                            content_type="text",
                            task_id=task_id,
                            secrets_manager=secrets_manager,
                            cache_service=cache_service
                        )
                        
                        # Check if sanitization failed (returned None or empty)
                        # None indicates sanitization failed (LLM call error, etc.)
                        # Empty string indicates content was blocked (high risk detected)
                        if sanitized_toon is None:
                            error_msg = f"[{task_id}] Content sanitization failed: sanitization returned None. This indicates a critical security failure (LLM call failed) - request cannot proceed with unsanitized external content."
                            logger.error(error_msg)
                            return (request_id, [], f"Query '{search_query}': Content sanitization failed - LLM call failed, cannot proceed with unsanitized external content")
                        
                        if not sanitized_toon or not sanitized_toon.strip():
                            error_msg = f"[{task_id}] Content sanitization blocked: sanitization returned empty. This indicates high prompt injection risk was detected - content blocked for security."
                            logger.error(error_msg)
                            return (request_id, [], f"Query '{search_query}': Content sanitization blocked - high prompt injection risk detected, content blocked")
                        
                        # Decode sanitized TOON back to Python dict for processing
                        # Try strict mode first, then fall back to lenient mode if that fails
                        sanitized_data = None
                        try:
                            # First attempt: strict mode for validation
                            try:
                                sanitized_data = decode(sanitized_toon, DecodeOptions(indent=2, strict=True))
                            except (ValueError, Exception) as decode_error:
                                logger.warning(f"[{task_id}] Strict TOON decode failed: {decode_error}. Attempting lenient decode...")
                                # Fallback: lenient mode to handle potential format variations from LLM sanitization
                                sanitized_data = decode(sanitized_toon, DecodeOptions(indent=2, strict=False))
                                logger.info(f"[{task_id}] Lenient TOON decode succeeded. Sanitized content may have minor format variations.")
                            
                            # Validate that decoded data is a dict with expected structure
                            if not isinstance(sanitized_data, dict):
                                raise ValueError(f"Decoded TOON data is not a dict, got {type(sanitized_data)}")
                            if "results" not in sanitized_data:
                                raise ValueError("Decoded TOON data missing 'results' key")
                            if not isinstance(sanitized_data["results"], list):
                                raise ValueError(f"Decoded TOON 'results' is not a list, got {type(sanitized_data['results'])}")
                            
                            # Validate all results are dicts - if any are not, log detailed info and fail
                            sanitized_results = sanitized_data.get("results", [])
                            invalid_indices = []
                            for i, result in enumerate(sanitized_results):
                                if not isinstance(result, dict):
                                    invalid_indices.append((i, type(result).__name__, str(result)[:100] if result else "None"))
                            
                            if invalid_indices:
                                error_details = "; ".join([f"idx {idx}: {type_name} ({value})" for idx, type_name, value in invalid_indices])
                                error_msg = f"[{task_id}] Invalid sanitized TOON structure: {len(invalid_indices)} result(s) are not dicts: {error_details}"
                                logger.error(error_msg)
                                logger.error(f"[{task_id}] Sanitized TOON (first 2000 chars): {sanitized_toon[:2000]}")
                                logger.error(f"[{task_id}] Decoded data structure: {json.dumps(sanitized_data, indent=2)[:2000]}")
                                raise ValueError(f"Sanitized TOON decode produced invalid structure: {len(invalid_indices)} result(s) are not dicts")
                                
                        except Exception as e:
                            error_msg = f"[{task_id}] Failed to decode sanitized TOON or invalid structure: {e}"
                            logger.error(error_msg, exc_info=True)
                            logger.error(f"[{task_id}] Sanitized TOON content (first 3000 chars):\n{sanitized_toon[:3000]}")
                            return (request_id, [], f"Query '{search_query}': Failed to decode sanitized TOON content - format may be corrupted: {str(e)}")
                        
                        # Map sanitized content back to results
                        sanitized_results = sanitized_data.get("results", [])
                        
                        # Log the structure for debugging
                        logger.debug(f"[{task_id}] Decoded {len(sanitized_results)} sanitized results. All are dicts: {all(isinstance(r, dict) for r in sanitized_results)}")
                        
                        for idx, metadata in enumerate(result_metadata):
                            # Get sanitized content
                            sanitized_result = sanitized_results[idx] if idx < len(sanitized_results) else None
                            
                            # This should never happen now due to validation above, but keep as safety check
                            if not isinstance(sanitized_result, dict):
                                error_msg = f"[{task_id}] Search result {idx} sanitized data is not a dict, got {type(sanitized_result)}. This should not happen after validation."
                                logger.error(error_msg)
                                continue
                            
                            sanitized_title = sanitized_result.get("title", "").strip() if isinstance(sanitized_result.get("title"), str) else ""
                            sanitized_description = sanitized_result.get("description", "").strip() if isinstance(sanitized_result.get("description"), str) else ""
                            # Parse extra_snippets back from pipe-delimited string
                            extra_snippets_str = sanitized_result.get("extra_snippets", "")
                            sanitized_extra_snippets = extra_snippets_str.split("|") if extra_snippets_str else []
                            
                            # If sanitization returned empty, use original (but log warning)
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Search result {idx} title empty after sanitization, using original: {metadata.get('url', 'unknown')}")
                                sanitized_title = metadata["original_title"]
                            
                            if not sanitized_description or not sanitized_description.strip():
                                sanitized_description = metadata["original_description"]
                            
                            # Skip result if title was blocked (high risk - empty after sanitization)
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Search result {idx} title blocked due to prompt injection risk: {metadata.get('url', 'unknown')}")
                                continue
                            
                            # Build preview with sanitized content
                            preview = {
                                "type": "search_result",
                                "title": sanitized_title,
                                "url": metadata["url"],
                                "description": sanitized_description,
                                "page_age": metadata["page_age"],
                                "profile": {
                                    "name": metadata["profile_name"]
                                } if metadata["profile_name"] else None,
                                "meta_url": {
                                    "favicon": metadata["favicon"]
                                } if metadata["favicon"] else None,
                                "thumbnail": {
                                    "original": metadata["thumbnail_original"]
                                } if metadata["thumbnail_original"] else None,
                                "extra_snippets": sanitized_extra_snippets,
                                "hash": self._generate_result_hash(metadata["url"])
                            }
                            
                            # INFO log to verify thumbnail/favicon are being included in preview
                            logger.info(
                                f"[{task_id}] [SEARCH_DEBUG] Preview {idx} built: "
                                f"metadata_favicon={metadata.get('favicon')}, "
                                f"metadata_thumbnail_original={metadata.get('thumbnail_original')}, "
                                f"preview_meta_url={preview.get('meta_url')}, "
                                f"preview_thumbnail={preview.get('thumbnail')}"
                            )
                            
                            previews.append(preview)
                    
                    except Exception as e:
                        error_msg = f"[{task_id}] Error encoding/decoding TOON format: {e}"
                        logger.error(error_msg, exc_info=True)
                        return (request_id, [], f"Query '{search_query}': TOON encoding/decoding error - {str(e)}")
                else:
                    # No text content to sanitize - add results with HTML tags stripped (shouldn't happen but handle it)
                    logger.warning(f"[{task_id}] No text content found in search results to sanitize")
                    for idx, result in enumerate(results):
                        meta_url = result.get("meta_url", {})
                        favicon = meta_url.get("favicon") if isinstance(meta_url, dict) else None
                        profile = result.get("profile", {})
                        profile_name = profile.get("name") if isinstance(profile, dict) else None
                        thumbnail = result.get("thumbnail", {})
                        thumbnail_original = thumbnail.get("original") if isinstance(thumbnail, dict) else None
                        
                        # Strip HTML tags even in fallback case
                        raw_extra_snippets = result.get("extra_snippets", [])
                        if not isinstance(raw_extra_snippets, list):
                            raw_extra_snippets = []
                        
                        preview = {
                            "type": "search_result",
                            "title": strip_html_tags(result.get("title", "")),
                            "url": result.get("url", ""),
                            "description": strip_html_tags(result.get("description", "")),
                            "page_age": result.get("page_age", result.get("age", "")),
                            "profile": {"name": profile_name} if profile_name else None,
                            "meta_url": {"favicon": favicon} if favicon else None,
                            "thumbnail": {"original": thumbnail_original} if thumbnail_original else None,
                            "extra_snippets": [strip_html_tags(s) for s in raw_extra_snippets if s],
                            "hash": self._generate_result_hash(result.get("url", ""))
                        }
                        previews.append(preview)
            
            logger.info(f"Search (id: {request_id}) completed: {len(previews)} results for '{search_query}'")
            return (request_id, previews, None)
            
        except Exception as e:
            error_msg = f"Query '{search_query}' (id: {request_id}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)
    
    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs
    ) -> SearchResponse:
        """
        Execute web search skill.
        
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
        1. Request received in FastAPI route handler (app-web container)
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

