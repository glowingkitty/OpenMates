# backend/apps/web/skills/read_skill.py
#
# Web read skill implementation.
# Provides web page reading functionality using the Firecrawl API.
#
# This skill supports multiple URLs in a single request,
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
from backend.shared.providers.firecrawl.firecrawl_scrape import scrape_url
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content, check_rate_limit, wait_for_rate_limit
# RateLimitScheduledException is no longer caught here - it bubbles up to route handler
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


class ReadRequest(BaseModel):
    """
    Request model for web read skill.
    Always uses 'requests' array format for consistency and parallel processing support.
    Each request specifies its own parameters with defaults defined in the tool_schema.
    """
    # Multiple URLs (standard format per REST API architecture)
    requests: List[Dict[str, Any]] = Field(
        ...,
        description="Array of read request objects. Each object must contain 'url' and can include optional parameters (formats, only_main_content, max_age, timeout) with defaults from schema."
    )


class ReadResult(BaseModel):
    """Individual read result model."""
    url: str
    title: Optional[str] = None
    markdown: Optional[str] = None
    # HTML removed: not needed for LLM and significantly increases payload size
    # html: Optional[str] = None
    # Summary removed: not needed and reduces payload size
    # summary: Optional[str] = None
    # Metadata removed: specific fields moved to root level
    # metadata: Optional[Dict[str, Any]] = None
    # Fields moved from metadata to root level for easier access
    language: Optional[str] = None
    favicon: Optional[str] = None
    og_image: Optional[str] = None
    og_sitename: Optional[str] = None
    error: Optional[str] = None


class ReadResponse(BaseModel):
    """Response model for web read skill."""
    # Results are grouped by request id - each entry contains 'id' and 'results' array
    # This structure allows clients to match responses to original requests without redundant data
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' (matching request id) and 'results' array with actual read results for that request."
    )
    provider: str = Field(
        default="Firecrawl",
        description="The provider used (e.g., 'Firecrawl')"
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on read results"
    )
    error: Optional[str] = Field(None, description="Error message if read failed")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "favicon",  # Favicon URL not needed for LLM inference
            "og_image",  # OG image URL not needed for LLM inference
            "og_sitename",  # OG site name not needed for LLM inference
        ],
        description="List of field paths (supports dot notation) that should be excluded from LLM inference to reduce token usage. These fields are preserved in chat history for UI rendering but filtered out before sending to LLM. Note: Metadata object is removed - specific fields are moved to root level."
    )
    # preview_data removed: redundant metadata that can be derived from results
    # preview_data: Optional[Dict[str, Any]] = Field(
    #     None,
    #     description="Preview data for frontend rendering. This is skill-specific metadata for UI display (e.g., url, result_count, etc.). Does NOT include actual results - those are in 'results' field."
    # )


class ReadSkill(BaseSkill):
    """
    Web read skill that uses Firecrawl API to read/scrape web pages.
    
    Supports multiple URLs in a single request, processing them in parallel.
    Each URL is scraped independently and results are combined.
    
    ARCHITECTURE DECISION: Direct Async Execution vs Celery Tasks
    ==============================================================
    
    This skill executes directly in the FastAPI route handler (app-web container) using
    async/await, rather than dispatching to a Celery task in app-web-worker. This is an
    intentional architectural decision for the following reasons:
    
    1. **Performance & Latency**
       - Web scraping is a quick operation (typically 1-5 seconds)
       - Direct async execution has ~0ms overhead vs Celery's ~50-200ms overhead
         (task dispatch + queue wait + result retrieval)
       - Users expect immediate results for read requests
    
    2. **Non-Blocking Concurrency**
       - The execute() method uses async/await, making it non-blocking
       - FastAPI's event loop can handle thousands of concurrent requests efficiently
       - During I/O operations (HTTP calls to Firecrawl API, content sanitization), the
         event loop yields control, allowing other requests to be processed
       - This is NOT blocking - multiple requests are processed concurrently
    
    3. **I/O-Bound Nature**
       - Web scraping is primarily I/O-bound (network calls, not CPU-intensive)
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
    - Web read/scraping (quick, I/O-bound)
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
                 # This is for ReadSkill's specific operational defaults from its 'default_config' block in app.yml
                 skill_operational_defaults: Optional[Dict[str, Any]] = None
                 ):
        """
        Initialize ReadSkill.
        
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
        # Currently ReadSkill doesn't use operational defaults, but we accept it for consistency
        if skill_operational_defaults:
            logger.debug(f"ReadSkill '{self.skill_name}' received operational_defaults: {skill_operational_defaults}")
            # Future: Parse and use skill_operational_defaults if ReadSkill needs specific config
        
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
            
            # Find the read skill in the skills list
            skills = app_config.get("skills", [])
            for skill in skills:
                if skill.get("id", "").strip() == "read":
                    suggestions = skill.get("suggestions_follow_up_requests", [])
                    if suggestions and isinstance(suggestions, list):
                        self.suggestions_follow_up_requests = [str(s) for s in suggestions]
                        logger.debug(f"Loaded {len(self.suggestions_follow_up_requests)} follow-up suggestions from app.yml")
                        return
                    else:
                        logger.warning(f"Follow-up suggestions not found or invalid in app.yml for read skill, suggestions_follow_up_requests will be empty")
                        self.suggestions_follow_up_requests = []
                        return
            
            # If read skill not found
            logger.error(f"Read skill not found in app.yml, suggestions_follow_up_requests will be empty")
            self.suggestions_follow_up_requests = []
            
        except Exception as e:
            logger.error(f"Error loading follow-up suggestions from app.yml: {e}", exc_info=True)
            self.suggestions_follow_up_requests = []
    
    async def _process_single_read_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
        cache_service: CacheService
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str]]:
        """
        Process a single web read request.
        
        This method handles all the logic for processing one web read request:
        - Parameter extraction and validation
        - Rate limit checking
        - API call to Firecrawl
        - Content sanitization
        - Result formatting
        
        Args:
            req: Request dictionary with url and optional parameters
            request_id: The id of this request (for matching in response)
            secrets_manager: SecretsManager instance
            cache_service: CacheService instance for rate limiting
        
        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
            - request_id: The id of the request (for grouping in response)
            - results_list: List containing single read result (empty if error)
            - error_string_or_none: Error message if processing failed, None if successful
        """
        # Extract URL and parameters from request
        read_url = req.get("url")
        if not read_url:
            return (request_id, [], f"Missing 'url' parameter")
        
        # Extract request-specific parameters (with defaults from schema)
        req_formats = req.get("formats", ["markdown"])
        req_only_main_content = req.get("only_main_content", True)
        req_max_age = req.get("max_age")
        req_timeout = req.get("timeout")
        
        logger.debug(f"Executing web read (id: {request_id}): url='{read_url}', formats={req_formats}")
        
        try:
            # Check and enforce rate limits before calling external API
            provider_id = "firecrawl"
            skill_id = "read"
            
            # Check rate limit
            is_allowed, retry_after = await check_rate_limit(
                provider_id=provider_id,
                skill_id=skill_id,
                cache_service=cache_service
            )
            
            # If rate limited, wait for the limit to reset
            if not is_allowed:
                logger.info(f"Rate limit hit for web read '{read_url}' (id: {request_id}), waiting for reset...")
                try:
                    celery_producer = None
                    celery_task_context = None
                    if hasattr(self.app, 'celery_producer') and self.app.celery_producer:
                        celery_producer = self.app.celery_producer
                        celery_task_context = {
                            "app_id": self.app_id,
                            "skill_id": self.skill_id,
                            "arguments": {
                                "url": read_url,
                                "formats": req_formats,
                                "only_main_content": req_only_main_content,
                                "max_age": req_max_age,
                                "timeout": req_timeout
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
            
            # Call Firecrawl API
            scrape_result = await scrape_url(
                url=read_url,
                secrets_manager=secrets_manager,
                formats=req_formats,
                only_main_content=req_only_main_content,
                max_age=req_max_age,
                timeout=req_timeout,
                sanitize_output=True
            )
            
            if scrape_result.get("error"):
                return (request_id, [], f"URL '{read_url}': {scrape_result['error']}")
            
            # Check if sanitization should be skipped
            should_sanitize = scrape_result.get("sanitize_output", True)
            
            # Extract data from scrape result
            data = scrape_result.get("data", {})
            metadata = data.get("metadata", {})
            title = metadata.get("title", "") if isinstance(metadata, dict) else ""
            markdown = data.get("markdown", "")
            
            # Extract specific fields from metadata
            language = None
            favicon = None
            og_image = None
            og_sitename = None
            
            if isinstance(metadata, dict):
                language = metadata.get("language")
                favicon = metadata.get("favicon")
                og_image = metadata.get("ogImage") or metadata.get("og:image")
                og_sitename = metadata.get("ogSiteName") or metadata.get("og:site_name")
            
            # Build result with sanitized content
            task_id = f"read_{request_id}_{read_url[:50]}"
            
            # Build JSON structure with only text fields that need sanitization
            text_data_for_sanitization = {
                "title": title,
                "markdown": markdown
            }
            
            # Skip sanitization if sanitize_output=False
            if not should_sanitize:
                logger.debug(f"[{task_id}] Sanitization skipped (sanitize_output=False), using raw results")
                result = {
                    "type": "read_result",
                    "url": read_url,
                    "title": title,
                    "markdown": markdown,
                    "language": language,
                    "favicon": favicon,
                    "og_image": og_image,
                    "og_sitename": og_sitename,
                    "hash": self._generate_result_hash(read_url)
                }
                return (request_id, [result], None)
            else:
                # Convert JSON to TOON format and sanitize
                try:
                    toon_text = encode(text_data_for_sanitization)
                    logger.info(f"[{task_id}] Encoding web read content into TOON format ({len(toon_text)} chars, ~{len(toon_text)/4:.0f} tokens)")
                    
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
                        return (request_id, [], f"URL '{read_url}': Content sanitization failed - LLM call failed")
                    
                    if not sanitized_toon or not sanitized_toon.strip():
                        error_msg = f"[{task_id}] Content sanitization blocked: sanitization returned empty."
                        logger.error(error_msg)
                        return (request_id, [], f"URL '{read_url}': Content sanitization blocked - high prompt injection risk detected")
                    
                    # Decode sanitized TOON back to Python dict
                    sanitized_data = None
                    try:
                        try:
                            sanitized_data = decode(sanitized_toon, DecodeOptions(indent=2, strict=True))
                        except (ValueError, Exception) as decode_error:
                            logger.warning(f"[{task_id}] Strict TOON decode failed: {decode_error}. Attempting lenient decode...")
                            sanitized_data = decode(sanitized_toon, DecodeOptions(indent=2, strict=False))
                            logger.info(f"[{task_id}] Lenient TOON decode succeeded.")
                        
                        if not isinstance(sanitized_data, dict):
                            raise ValueError("Invalid sanitized TOON structure")
                            
                    except Exception as e:
                        error_msg = f"[{task_id}] Failed to decode sanitized TOON: {e}"
                        logger.error(error_msg, exc_info=True)
                        return (request_id, [], f"URL '{read_url}': Failed to decode sanitized TOON content - {str(e)}")
                    
                    # Extract sanitized content
                    sanitized_title = sanitized_data.get("title", "").strip() if isinstance(sanitized_data.get("title"), str) else ""
                    sanitized_markdown = sanitized_data.get("markdown", "").strip() if isinstance(sanitized_data.get("markdown"), str) else ""
                    
                    if not sanitized_title or not sanitized_title.strip():
                        logger.warning(f"[{task_id}] Web read title empty after sanitization, using original")
                        sanitized_title = title
                    
                    if not sanitized_markdown or not sanitized_markdown.strip():
                        sanitized_markdown = markdown
                    
                    # Build result with sanitized content
                    result = {
                        "type": "read_result",
                        "url": read_url,
                        "title": sanitized_title,
                        "markdown": sanitized_markdown,
                        "language": language,
                        "favicon": favicon,
                        "og_image": og_image,
                        "og_sitename": og_sitename,
                        "hash": self._generate_result_hash(read_url)
                    }
                    
                    logger.info(f"Web read (id: {request_id}) completed: url='{read_url}'")
                    return (request_id, [result], None)
                
                except Exception as e:
                    error_msg = f"[{task_id}] Error encoding/decoding TOON format: {e}"
                    logger.error(error_msg, exc_info=True)
                    return (request_id, [], f"URL '{read_url}': TOON encoding/decoding error - {str(e)}")
            
        except Exception as e:
            error_msg = f"URL '{read_url}' (id: {request_id}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)
    
    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None
    ) -> ReadResponse:
        """
        Execute web read skill.
        
        Always uses 'requests' array format for consistency and parallel processing support.
        Each request in the array specifies its own parameters with defaults defined in the schema.
        
        NOTE: This method executes directly in the FastAPI route handler (not via Celery).
        This is intentional - see class docstring for architecture decision rationale.
        The async/await pattern ensures non-blocking execution and excellent concurrency.
        
        Args:
            requests: Array of read request objects. Each object must contain 'url' and can include optional parameters (formats, only_main_content, max_age, timeout).
            secrets_manager: SecretsManager instance (injected by app)
        
        Returns:
            ReadResponse with results and optional follow-up suggestions
        
        Execution Flow:
        --------------
        1. Request received in FastAPI route handler (app-web container)
        2. This async method is called directly (no Celery dispatch)
        3. I/O operations (Firecrawl API calls, content sanitization) use await
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
            skill_name="ReadSkill",
            error_response_factory=lambda msg: ReadResponse(results=[], error=msg),
            logger=logger
        )
        if error_response:
            return error_response
        
        # Validate requests array using BaseSkill helper
        validated_requests, error = self._validate_requests_array(
            requests=requests,
            required_field="url",
            field_display_name="url",
            empty_error_message="No read requests provided. 'requests' array must contain at least one request with a 'url' field.",
            logger=logger
        )
        if error:
            return ReadResponse(results=[], error=error)
        
        # Initialize cache service for rate limiting (shared across all requests)
        cache_service = CacheService()
        
        # Process all read requests in parallel using BaseSkill helper
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_read_request,
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
            response_class=ReadResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Firecrawl",
            suggestions=self.suggestions_follow_up_requests,
            logger=logger
        )
        
        return response
    
    # _generate_result_hash is now provided by BaseSkill
