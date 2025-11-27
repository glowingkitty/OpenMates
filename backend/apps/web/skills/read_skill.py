# backend/apps/web/skills/read_skill.py
#
# Web read skill implementation.
# Provides web page reading functionality using the Firecrawl API.
#
# This skill supports multiple URLs in a single request,
# processing them in parallel (up to 9 parallel requests).

import logging
import os
import json
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting
from toon_format import encode, decode, DecodeOptions

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.firecrawl.firecrawl_scrape import scrape_url
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content, check_rate_limit, wait_for_rate_limit
from backend.apps.ai.processing.rate_limiting import RateLimitScheduledException
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
    # Results are returned directly (not nested in 'previews')
    # The main_processor will extract these and structure them as app_skill_use.output
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of read results. These will be flattened and encoded to TOON format by main_processor."
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
                    logger.debug("ReadSkill initialized its own SecretsManager instance")
                except Exception as e:
                    logger.error(f"Failed to initialize SecretsManager for ReadSkill: {e}", exc_info=True)
                    return ReadResponse(
                        results=[],
                        error="Read service configuration error: Failed to initialize secrets manager"
                    )
        
        # Validate requests array
        if not requests or len(requests) == 0:
            logger.error("No requests provided to ReadSkill")
            return ReadResponse(
                results=[],
                error="No read requests provided. 'requests' array must contain at least one request with a 'url' field."
            )
        
        # Validate that all requests have a url
        for i, req in enumerate(requests):
            if not req.get("url"):
                logger.error(f"Request {i+1} in requests array is missing 'url' field")
                return ReadResponse(
                    results=[],
                    error=f"Request {i+1} is missing required 'url' field"
                )
        
        read_requests = requests
        
        # Process all read requests
        all_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        
        for i, req in enumerate(read_requests):
            # Extract URL and parameters from request
            read_url = req.get("url")
            if not read_url:
                errors.append(f"Request {i+1}: Missing 'url' parameter")
                continue
            
            # Extract request-specific parameters (with defaults from schema)
            req_formats = req.get("formats", ["markdown"])  # Default from schema
            req_only_main_content = req.get("only_main_content", True)  # Default from schema
            req_max_age = req.get("max_age")  # Optional
            req_timeout = req.get("timeout")  # Optional
            
            logger.debug(f"Executing read {i+1}/{len(read_requests)}: url='{read_url}', formats={req_formats}")
            
            try:
                # Check and enforce rate limits before calling external API
                # According to app_skills.md: "Requests are never rejected due to rate limits.
                # Instead, they're queued and processed when limits allow."
                provider_id = "firecrawl"  # Firecrawl provider
                skill_id = "read"
                
                # Check rate limit
                cache_service = CacheService()
                is_allowed, retry_after = await check_rate_limit(
                    provider_id=provider_id,
                    skill_id=skill_id,
                    cache_service=cache_service
                )
                
                # If rate limited, wait for the limit to reset
                if not is_allowed:
                    logger.info(f"Rate limit hit for read '{read_url}', waiting for reset...")
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
                                    "url": read_url,
                                    "formats": req_formats,
                                    "only_main_content": req_only_main_content,
                                    "max_age": req_max_age,
                                    "timeout": req_timeout
                                }
                            }
                        
                        await wait_for_rate_limit(
                            provider_id=provider_id,
                            skill_id=skill_id,
                            cache_service=cache_service,
                            celery_producer=celery_producer,
                            celery_task_context=celery_task_context
                        )
                    except RateLimitScheduledException as e:
                        # Task was scheduled via Celery - this shouldn't happen in inline execution
                        # but if it does, we'll log and skip this read
                        logger.warning(
                            f"Read '{read_url}' was scheduled via Celery (task_id: {e.task_id}) "
                            f"due to rate limit. This read will be processed asynchronously."
                        )
                        # Skip this read request as it's been scheduled
                        continue
                
                # Call Firecrawl API
                # sanitize_output defaults to True for user-facing requests (sanitization required)
                scrape_result = await scrape_url(
                    url=read_url,
                    secrets_manager=secrets_manager,
                    formats=req_formats,
                    only_main_content=req_only_main_content,
                    max_age=req_max_age,
                    timeout=req_timeout,
                    sanitize_output=True  # Enable sanitization for user-facing requests (default)
                )
                
                if scrape_result.get("error"):
                    errors.append(f"URL '{read_url}': {scrape_result['error']}")
                    continue
                
                # Check if sanitization should be skipped (e.g., for health checks)
                should_sanitize = scrape_result.get("sanitize_output", True)  # Default to True for safety
                
                # Extract data from scrape result
                data = scrape_result.get("data", {})
                metadata = data.get("metadata", {})
                title = metadata.get("title", "") if isinstance(metadata, dict) else ""
                markdown = data.get("markdown", "")
                # HTML is removed entirely - not needed for LLM and significantly increases payload size
                # html = data.get("html")  # Removed: HTML is redundant (markdown is sufficient) and very large
                # Summary removed: not needed and reduces payload size
                # summary = data.get("summary")
                
                # Extract specific fields from metadata to add to root level of result
                # These fields are moved from metadata to root level for easier access
                language = None
                favicon = None
                og_image = None
                og_sitename = None
                
                if isinstance(metadata, dict):
                    # Extract language
                    language = metadata.get("language")
                    
                    # Extract favicon
                    favicon = metadata.get("favicon")
                    
                    # Extract OG image (try both formats: ogImage and og:image)
                    og_image = metadata.get("ogImage") or metadata.get("og:image")
                    
                    # Extract OG site name (try both formats: ogSiteName and og:site_name)
                    og_sitename = metadata.get("ogSiteName") or metadata.get("og:site_name")
                
                # Build result with sanitized content
                # Batch all text content into a single sanitization request using TOON format
                task_id = f"read_{i+1}_{read_url[:50]}"  # Limit length for logging
                
                # Build JSON structure with only text fields that need sanitization
                # Summary removed: not needed and reduces payload size
                text_data_for_sanitization = {
                    "title": title,
                    "markdown": markdown
                }
                
                # Skip sanitization if sanitize_output=False (e.g., for health checks)
                if not should_sanitize:
                    logger.debug(f"[{task_id}] Sanitization skipped (sanitize_output=False), using raw results")
                    # Use raw results without sanitization
                    result = {
                        "type": "read_result",
                        "url": read_url,
                        "title": title,
                        "markdown": markdown,
                        # HTML removed: not needed for LLM and significantly increases payload size
                        # Summary removed: not needed and reduces payload size
                        # Metadata removed: specific fields moved to root level
                        "language": language,
                        "favicon": favicon,
                        "og_image": og_image,
                        "og_sitename": og_sitename,
                        "hash": self._generate_result_hash(read_url)
                    }
                    all_results.append(result)
                else:
                    # Convert JSON to TOON format using toon-format package
                    if text_data_for_sanitization.get("markdown") or text_data_for_sanitization.get("title"):
                        try:
                            # Encode to TOON format
                            toon_text = encode(text_data_for_sanitization)
                            
                            logger.info(f"[{task_id}] Batching read result into TOON-format sanitization request ({len(toon_text)} chars, ~{len(toon_text)/4:.0f} tokens)")
                            logger.debug(f"[{task_id}] TOON format data (full):\n{toon_text}")
                            
                            # Sanitize all text content in one request (preserves TOON format)
                            sanitized_toon = await sanitize_external_content(
                                content=toon_text,
                                content_type="text",
                                task_id=task_id,
                                secrets_manager=secrets_manager
                            )
                            
                            # Check if sanitization failed (returned None or empty)
                            # None indicates sanitization failed (LLM call error, etc.)
                            # Empty string indicates content was blocked (high risk detected)
                            if sanitized_toon is None:
                                error_msg = f"[{task_id}] Content sanitization failed: sanitization returned None. This indicates a critical security failure (LLM call failed) - request cannot proceed with unsanitized external content."
                                logger.error(error_msg)
                                errors.append(f"URL '{read_url}': Content sanitization failed - LLM call failed, cannot proceed with unsanitized external content")
                                continue
                            
                            if not sanitized_toon or not sanitized_toon.strip():
                                error_msg = f"[{task_id}] Content sanitization blocked: sanitization returned empty. This indicates high prompt injection risk was detected - content blocked for security."
                                logger.error(error_msg)
                                errors.append(f"URL '{read_url}': Content sanitization blocked - high prompt injection risk detected, content blocked")
                                continue
                            
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
                                
                                # Validate that decoded data is a dict
                                if not isinstance(sanitized_data, dict):
                                    raise ValueError(f"Decoded TOON data is not a dict, got {type(sanitized_data)}")
                                    
                            except Exception as e:
                                error_msg = f"[{task_id}] Failed to decode sanitized TOON or invalid structure: {e}"
                                logger.error(error_msg, exc_info=True)
                                logger.error(f"[{task_id}] Sanitized TOON content (first 3000 chars):\n{sanitized_toon[:3000]}")
                                errors.append(f"URL '{read_url}': Failed to decode sanitized TOON content - format may be corrupted: {str(e)}")
                                continue
                            
                            # Extract sanitized content
                            sanitized_title = sanitized_data.get("title", "").strip() if isinstance(sanitized_data.get("title"), str) else ""
                            sanitized_markdown = sanitized_data.get("markdown", "").strip() if isinstance(sanitized_data.get("markdown"), str) else ""
                            # Summary removed: not needed and reduces payload size
                            
                            # If sanitization returned empty, use original (but log warning)
                            if not sanitized_title or not sanitized_title.strip():
                                logger.warning(f"[{task_id}] Title empty after sanitization, using original: {read_url}")
                                sanitized_title = title
                            
                            if not sanitized_markdown or not sanitized_markdown.strip():
                                sanitized_markdown = markdown
                            
                            # Skip result if markdown was blocked (high risk - empty after sanitization)
                            if not sanitized_markdown or not sanitized_markdown.strip():
                                logger.warning(f"[{task_id}] Markdown blocked due to prompt injection risk: {read_url}")
                                continue
                            
                            # Build result with sanitized content
                            result = {
                                "type": "read_result",
                                "url": read_url,
                                "title": sanitized_title,
                                "markdown": sanitized_markdown,
                                # HTML removed: not needed for LLM and significantly increases payload size
                                # Summary removed: not needed and reduces payload size
                                # Metadata removed: specific fields moved to root level
                                "language": language,
                                "favicon": favicon,
                                "og_image": og_image,
                                "og_sitename": og_sitename,
                                "hash": self._generate_result_hash(read_url)
                            }
                            all_results.append(result)
                        
                        except Exception as e:
                            error_msg = f"[{task_id}] Error encoding/decoding TOON format: {e}"
                            logger.error(error_msg, exc_info=True)
                            errors.append(f"URL '{read_url}': TOON encoding/decoding error - {str(e)}")
                            continue
                    else:
                        # No text content to sanitize - add result as-is (shouldn't happen but handle it)
                        logger.warning(f"[{task_id}] No text content found in read result to sanitize")
                        result = {
                            "type": "read_result",
                            "url": read_url,
                            "title": title,
                            "markdown": markdown,
                            # HTML removed: not needed for LLM and significantly increases payload size
                            # Summary removed: not needed and reduces payload size
                            # Metadata removed: specific fields moved to root level
                            "language": language,
                            "favicon": favicon,
                            "og_image": og_image,
                            "og_sitename": og_sitename,
                            "hash": self._generate_result_hash(read_url)
                        }
                        all_results.append(result)
                
                logger.info(f"Read {i+1}/{len(read_requests)} completed: successfully read '{read_url}'")
                
            except Exception as e:
                error_msg = f"URL '{read_url}': {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
        
        # Use follow-up suggestions loaded from app.yml
        # Only include suggestions if we have results and suggestions are configured
        suggestions = None
        if len(all_results) > 0 and self.suggestions_follow_up_requests:
            suggestions = self.suggestions_follow_up_requests
        
        # preview_data removed: redundant metadata that can be derived from results
        # - result_count: len(all_results)
        # - completed_count/total_count: len(read_requests)
        # - url: all_results[0].url if results exist
        # Frontend can derive all this from the results array itself
        
        # Build response:
        # - results: actual read results (will be flattened and encoded to TOON by main_processor)
        # - provider: at root level
        response = ReadResponse(
            results=all_results,  # Results directly (not nested in 'previews')
            provider="Firecrawl",  # Provider at root level
            suggestions_follow_up_requests=suggestions
            # preview_data removed: redundant metadata
        )
        
        # Add error message if there were errors (but still return results if any)
        if errors:
            response.error = "; ".join(errors)
            logger.warning(f"Read completed with {len(errors)} error(s): {response.error}")
        
        logger.info(f"Read skill execution completed: {len(all_results)} total results, {len(errors)} errors")
        return response
    
    def _generate_result_hash(self, url: str) -> str:
        """
        Generate a hash for a read result URL.
        Used for deduplication and tracking.
        
        Args:
            url: The result URL
        
        Returns:
            Hash string
        """
        import hashlib
        return hashlib.sha256(url.encode()).hexdigest()[:16]

