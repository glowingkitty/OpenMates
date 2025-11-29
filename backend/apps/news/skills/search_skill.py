# backend/apps/news/skills/search_skill.py
#
# News search skill implementation.
# Provides news search functionality using the Brave Search API.
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
from backend.shared.providers.brave.brave_search import search_news
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content, check_rate_limit, wait_for_rate_limit
# RateLimitScheduledException is no longer caught here - it bubbles up to route handler
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    """
    Request model for news search skill.
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
    """Response model for news search skill."""
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
    News search skill that uses Brave Search API to search for news articles.
    
    Supports multiple search queries in a single request, processing them in parallel.
    Each query is executed independently and results are combined.
    
    ARCHITECTURE DECISION: Direct Async Execution vs Celery Tasks
    ==============================================================
    
    This skill executes directly in the FastAPI route handler (app-news container) using
    async/await, rather than dispatching to a Celery task in app-news-worker. This is an
    intentional architectural decision for the following reasons:
    
    1. **Performance & Latency**
       - News search is a quick operation (typically 0.5-2 seconds)
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
       - Easier to debug and monitor (logs appear directly in app-news)
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
    - News search (quick, I/O-bound)
    - Quick API lookups
    - Simple data transformations
    - Fast external service calls
    
    Current Implementation:
    ----------------------
    - Executes in: app-news (FastAPI container)
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
        Process a single news search request.
        
        This method handles all the logic for processing one news search request:
        - Parameter extraction and validation
        - Rate limit checking
        - API call to Brave News Search
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
            return (request_id, [], f"Missing 'query' parameter")
        
        # Extract request-specific parameters (with defaults from schema)
        req_count = req.get("count", 10)  # Default from schema
        req_country_raw = req.get("country", "us")  # Default from schema
        req_lang = req.get("search_lang", "en")  # Default from schema
        req_safesearch = req.get("safesearch", "moderate")  # Default from schema
        # Default freshness to "pw" (past week) for news searches to prioritize recent content
        req_freshness = req.get("freshness", "pw")  # Default to past week for news
        
        # CRITICAL: Validate and correct country code to ensure it's valid for Brave Search API
        VALID_BRAVE_COUNTRY_CODES = {
            "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "GR", "HK", 
            "IN", "ID", "IT", "JP", "KR", "MY", "MX", "NL", "NZ", "NO", "CN", "PL", "PT", 
            "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW", "TR", "GB", "US", "ALL"
        }
        req_country_upper = req_country_raw.upper() if req_country_raw else "US"
        if req_country_upper not in VALID_BRAVE_COUNTRY_CODES:
            logger.warning(
                f"Invalid country code '{req_country_raw}' for news search '{search_query}' (id: {request_id}). "
                f"Valid codes: {sorted(VALID_BRAVE_COUNTRY_CODES)}. Falling back to 'us'."
            )
            req_country = "us"
        else:
            req_country = req_country_upper
        
        logger.debug(f"Executing news search (id: {request_id}): query='{search_query}', country='{req_country}'")
        
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
                logger.info(f"Rate limit hit for news search '{search_query}' (id: {request_id}), waiting for reset...")
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
                except Exception as e:
                    # Re-raise exceptions from wait_for_rate_limit (e.g., RateLimitScheduledException)
                    # These should bubble up to the route handler
                    raise
            
            # Call Brave News Search API
            search_result = await search_news(
                query=search_query,
                secrets_manager=secrets_manager,
                count=req_count,
                country=req_country,
                search_lang=req_lang,
                safesearch=req_safesearch,
                freshness=req_freshness,  # News API supports freshness parameter
                extra_snippets=True,
                sanitize_output=True
            )
            
            if search_result.get("error"):
                return (request_id, [], f"Query '{search_query}': {search_result['error']}")
            
            # Check if sanitization should be skipped
            should_sanitize = search_result.get("sanitize_output", True)
            
            # Convert results to preview format and sanitize external content
            results = search_result.get("results", [])
            task_id = f"news_search_{request_id}_{search_query[:50]}"
            
            # Build JSON structure with only text fields that need sanitization
            text_data_for_sanitization = {"results": []}
            result_metadata = []
            
            for idx, result in enumerate(results):
                title = result.get("title", "").strip()
                description = result.get("description", "").strip()
                extra_snippets = result.get("extra_snippets", [])
                if not isinstance(extra_snippets, list):
                    extra_snippets = []
                
                text_data_for_sanitization["results"].append({
                    "title": title,
                    "description": description,
                    "extra_snippets": extra_snippets
                })
                
                # Store non-text metadata
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
            
            # Skip sanitization if sanitize_output=False
            if not should_sanitize:
                logger.debug(f"[{task_id}] Sanitization skipped (sanitize_output=False), using raw results")
                for idx, result in enumerate(results):
                    preview = {
                        "type": "search_result",
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "description": result.get("description", ""),
                        "page_age": result.get("page_age", result.get("age", "")),
                        "profile": result.get("profile"),
                        "meta_url": result.get("meta_url"),
                        "thumbnail": result.get("thumbnail"),
                        "extra_snippets": result.get("extra_snippets", []),
                        "hash": self._generate_result_hash(result.get("url", ""))
                    }
                    previews.append(preview)
            else:
                # Convert JSON to TOON format and sanitize
                if text_data_for_sanitization["results"]:
                    try:
                        # Prepare data for TOON tabular format
                        toon_data_for_encoding = {"results": []}
                        for result in text_data_for_sanitization["results"]:
                            extra_snippets_str = "|".join(result.get("extra_snippets", [])) if isinstance(result.get("extra_snippets"), list) else ""
                            toon_data_for_encoding["results"].append({
                                "title": result.get("title", ""),
                                "description": result.get("description", ""),
                                "extra_snippets": extra_snippets_str
                            })
                        
                        toon_text = encode(toon_data_for_encoding)
                        logger.info(f"[{task_id}] Batching {len(results)} news search results into single TOON-format sanitization request ({len(toon_text)} chars, ~{len(toon_text)/4:.0f} tokens)")
                        
                        # Sanitize all text content in one request
                        sanitized_toon = await sanitize_external_content(
                            content=toon_text,
                            content_type="text",
                            task_id=task_id,
                            secrets_manager=secrets_manager
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
                            extra_snippets_str = sanitized_result.get("extra_snippets", "")
                            sanitized_extra_snippets = extra_snippets_str.split("|") if extra_snippets_str else []
                            
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Search result {idx} title empty after sanitization, using original")
                                sanitized_title = metadata["original_title"]
                            
                            if not sanitized_description or not sanitized_description.strip():
                                sanitized_description = metadata["original_description"]
                            
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Search result {idx} title blocked due to prompt injection risk")
                                continue
                            
                            # Build preview with sanitized content
                            preview = {
                                "type": "search_result",
                                "title": sanitized_title,
                                "url": metadata["url"],
                                "description": sanitized_description,
                                "page_age": metadata["page_age"],
                                "profile": {"name": metadata["profile_name"]} if metadata["profile_name"] else None,
                                "meta_url": {"favicon": metadata["favicon"]} if metadata["favicon"] else None,
                                "thumbnail": {"original": metadata["thumbnail_original"]} if metadata["thumbnail_original"] else None,
                                "extra_snippets": sanitized_extra_snippets,
                                "hash": self._generate_result_hash(metadata["url"])
                            }
                            previews.append(preview)
                    
                    except Exception as e:
                        error_msg = f"[{task_id}] Error encoding/decoding TOON format: {e}"
                        logger.error(error_msg, exc_info=True)
                        return (request_id, [], f"Query '{search_query}': TOON encoding/decoding error - {str(e)}")
                else:
                    logger.warning(f"[{task_id}] No text content found in news search results to sanitize")
                    for idx, result in enumerate(results):
                        meta_url = result.get("meta_url", {})
                        favicon = meta_url.get("favicon") if isinstance(meta_url, dict) else None
                        profile = result.get("profile", {})
                        profile_name = profile.get("name") if isinstance(profile, dict) else None
                        thumbnail = result.get("thumbnail", {})
                        thumbnail_original = thumbnail.get("original") if isinstance(thumbnail, dict) else None
                        
                        preview = {
                            "type": "search_result",
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "description": result.get("description", ""),
                            "page_age": result.get("page_age", result.get("age", "")),
                            "profile": {"name": profile_name} if profile_name else None,
                            "meta_url": {"favicon": favicon} if favicon else None,
                            "thumbnail": {"original": thumbnail_original} if thumbnail_original else None,
                            "extra_snippets": result.get("extra_snippets", []),
                            "hash": self._generate_result_hash(result.get("url", ""))
                        }
                        previews.append(preview)
            
            logger.info(f"News search (id: {request_id}) completed: {len(previews)} results for '{search_query}'")
            return (request_id, previews, None)
            
        except Exception as e:
            error_msg = f"Query '{search_query}' (id: {request_id}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)
    
    async def execute(
        self,
        request: SearchRequest,
        secrets_manager: Optional[SecretsManager] = None
    ) -> SearchResponse:
        """
        Execute news search skill.
        
        Always uses 'requests' array format for consistency and parallel processing support.
        Each request in the array specifies its own parameters with defaults defined in the schema.
        
        NOTE: This method executes directly in the FastAPI route handler (not via Celery).
        This is intentional - see class docstring for architecture decision rationale.
        The async/await pattern ensures non-blocking execution and excellent concurrency.
        
        Args:
            request: SearchRequest Pydantic model containing the requests array. Each request object must contain 'query' and can include optional parameters (count, country, search_lang, safesearch).
            secrets_manager: SecretsManager instance (injected by app)
        
        Returns:
            SearchResponse with previews and optional follow-up suggestions
        
        Execution Flow:
        --------------
        1. Request received in FastAPI route handler (app-news container)
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
        # Use injected secrets_manager or create a new one
        if secrets_manager is None:
            # Try to get from app if available
            if hasattr(self.app, 'secrets_manager') and self.app.secrets_manager:
                secrets_manager = self.app.secrets_manager
            else:
                # Create a new SecretsManager instance
                # Skills that need secrets should initialize their own SecretsManager
                try:
                    secrets_manager = SecretsManager()
                    await secrets_manager.initialize()
                    logger.debug("SearchSkill initialized its own SecretsManager instance")
                except Exception as e:
                    logger.error(f"Failed to initialize SecretsManager for SearchSkill: {e}", exc_info=True)
                    return SearchResponse(
                        results=[],
                        error="Search service configuration error: Failed to initialize secrets manager"
                    )
        
        # Extract requests array from Pydantic model
        # The Pydantic model validates the structure, but we still need to validate individual request items
        requests = request.requests
        
        # Validate requests array
        if not requests or len(requests) == 0:
            logger.error("No requests provided to SearchSkill")
            return SearchResponse(
                results=[],
                error="No search requests provided. 'requests' array must contain at least one request with a 'query' field."
            )
        
        # Validate that all requests have required fields: 'id' and 'query'
        # Use BaseSkill helper method for consistent validation across all skills
        request_ids = set()
        for i, req in enumerate(requests):
            # Validate and normalize request 'id' field using BaseSkill helper
            request_id, error = self._validate_and_normalize_request_id(
                req=req,
                request_index=i,
                total_requests=len(requests),
                request_ids=request_ids,
                logger=logger
            )
            if error:
                logger.error(f"Request {i+1} validation failed: {error}")
                return SearchResponse(
                    results=[],
                    error=error
                )
            
            # Validate 'query' field
            if not req.get("query"):
                logger.error(f"Request {i+1} (id: {request_id}) in requests array is missing 'query' field")
                return SearchResponse(
                    results=[],
                    error=f"Request {i+1} (id: {request_id}) is missing required 'query' field"
                )
        
        search_requests = requests
        
        # Initialize cache service for rate limiting (shared across all requests)
        cache_service = CacheService()
        
        # Process all search requests in parallel using asyncio.gather()
        # Each request is processed independently and results are grouped by request id
        logger.info(f"Processing {len(search_requests)} news search requests in parallel")
        tasks = [
            self._process_single_search_request(
                req=req,
                request_id=req.get("id"),
                secrets_manager=secrets_manager,
                cache_service=cache_service
            )
            for req in search_requests
        ]
        
        # Wait for all requests to complete (parallel execution)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and group by request id
        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        
        for result in results:
            if isinstance(result, Exception):
                # Handle exceptions from asyncio.gather
                error_msg = f"Unexpected error processing request: {str(result)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue
            
            request_id, previews, error = result
            
            if error:
                errors.append(error)
                # Still include the request in results (with empty results array) for consistency
                grouped_results.append({
                    "id": request_id,
                    "results": []
                })
            else:
                # Group results by request id
                grouped_results.append({
                    "id": request_id,
                    "results": previews
                })
        
        # Sort results by request order (maintain original request order in response)
        request_order = {req.get("id"): i for i, req in enumerate(search_requests)}
        grouped_results.sort(key=lambda x: request_order.get(x["id"], 999))
        
        # Use follow-up suggestions loaded from app.yml
        # Only include suggestions if we have results and suggestions are configured
        suggestions = None
        total_results = sum(len(group.get("results", [])) for group in grouped_results)
        if total_results > 0 and self.suggestions_follow_up_requests:
            suggestions = self.suggestions_follow_up_requests
        
        # Build response with grouped results structure:
        # - results: List of request results, each with 'id' and 'results' array
        # - provider: at root level
        response = SearchResponse(
            results=grouped_results,  # Grouped by request id
            provider="Brave Search",  # Provider at root level
            suggestions_follow_up_requests=suggestions
        )
        
        # Add error message if there were errors (but still return results if any)
        if errors:
            response.error = "; ".join(errors)
            logger.warning(f"News search completed with {len(errors)} error(s): {response.error}")
        
        logger.info(f"News search skill execution completed: {len(grouped_results)} request groups, {total_results} total results, {len(errors)} errors")
        return response
    
    def _generate_result_hash(self, url: str) -> str:
        """
        Generate a hash for a search result URL.
        Used for deduplication and tracking.
        
        Args:
            url: The result URL
        
        Returns:
            Hash string
        """
        import hashlib
        return hashlib.sha256(url.encode()).hexdigest()[:16]
