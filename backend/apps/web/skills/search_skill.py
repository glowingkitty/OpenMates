# backend/apps/web/skills/search_skill.py
#
# Web search skill implementation.
# Provides web search functionality using the Brave Search API.
#
# This skill supports multiple search queries in a single request,
# processing them in parallel (up to 9 parallel requests).

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.brave.brave_search import search_web
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.ai.processing.skill_executor import sanitize_external_content, check_rate_limit, wait_for_rate_limit
from backend.apps.ai.processing.rate_limiting import RateLimitScheduledException
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    """
    Request model for web search skill.
    Supports both single query and multiple queries via 'requests' array.
    """
    # Single query (for backward compatibility and simple cases)
    query: Optional[str] = Field(None, description="Single search query")
    
    # Multiple queries (standard format per REST API architecture)
    requests: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Array of search request objects. Each object can contain 'query' and optional parameters."
    )
    
    # Search parameters (applied to all requests if using 'requests' array)
    count: int = Field(10, ge=1, le=20, description="Number of results per query (max 20)")
    country: str = Field("us", description="Country code for localized results")
    search_lang: str = Field("en", description="Language code for search")
    safesearch: str = Field("moderate", description="Safe search level: 'off', 'moderate', or 'strict'")


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
    previews: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of search result previews for display in the UI"
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on search results"
    )
    error: Optional[str] = Field(None, description="Error message if search failed")


class SearchSkill(BaseSkill):
    """
    Web search skill that uses Brave Search API to search the web.
    
    Supports multiple search queries in a single request, processing them in parallel.
    Each query is executed independently and results are combined.
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
        
        self.secrets_manager: Optional[SecretsManager] = None
    
    async def execute(
        self,
        query: Optional[str] = None,
        requests: Optional[List[Dict[str, Any]]] = None,
        count: int = 10,
        country: str = "us",
        search_lang: str = "en",
        safesearch: str = "moderate",
        secrets_manager: Optional[SecretsManager] = None
    ) -> SearchResponse:
        """
        Execute web search skill.
        
        Supports two formats:
        1. Single query: {"query": "search term"}
        2. Multiple queries: {"requests": [{"query": "term1"}, {"query": "term2"}]}
        
        Args:
            query: Single search query (for backward compatibility)
            requests: Array of search request objects (standard format)
            count: Number of results per query
            country: Country code for localized results
            search_lang: Language code for search
            safesearch: Safe search level
            secrets_manager: SecretsManager instance (injected by app)
        
        Returns:
            SearchResponse with previews and optional follow-up suggestions
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
                        previews=[],
                        error="Search service configuration error: Failed to initialize secrets manager"
                    )
        
        # Determine if we have multiple requests or single request
        search_requests: List[Dict[str, Any]] = []
        
        if requests and len(requests) > 0:
            # Multiple requests format (standard REST API format)
            search_requests = requests
        elif query:
            # Single query format (backward compatibility)
            search_requests = [{"query": query}]
        else:
            logger.error("No query or requests provided to SearchSkill")
            return SearchResponse(
                previews=[],
                error="No search query provided"
            )
        
        # Process all search requests
        all_previews: List[Dict[str, Any]] = []
        errors: List[str] = []
        
        for i, req in enumerate(search_requests):
            # Extract query and parameters from request
            search_query = req.get("query") or req.get("q")
            if not search_query:
                errors.append(f"Request {i+1}: Missing 'query' parameter")
                continue
            
            # Use request-specific parameters or fall back to top-level parameters
            req_count = req.get("count", count)
            req_country = req.get("country", country)
            req_lang = req.get("search_lang", search_lang)
            req_safesearch = req.get("safesearch", safesearch)
            
            logger.debug(f"Executing search {i+1}/{len(search_requests)}: query='{search_query}'")
            
            try:
                # Check and enforce rate limits before calling external API
                # According to app_skills.md: "Requests are never rejected due to rate limits.
                # Instead, they're queued and processed when limits allow."
                provider_id = "brave"  # Brave Search provider
                skill_id = "search"
                
                # Check rate limit
                cache_service = CacheService()
                is_allowed, retry_after = await check_rate_limit(
                    provider_id=provider_id,
                    skill_id=skill_id,
                    cache_service=cache_service
                )
                
                # If rate limited, wait for the limit to reset
                if not is_allowed:
                    logger.info(f"Rate limit hit for search '{search_query}', waiting for reset...")
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
                        # but if it does, we'll log and skip this search
                        logger.warning(
                            f"Search '{search_query}' was scheduled via Celery (task_id: {e.task_id}) "
                            f"due to rate limit. This search will be processed asynchronously."
                        )
                        # Skip this search request as it's been scheduled
                        continue
                
                # Call Brave Search API
                search_result = await search_web(
                    query=search_query,
                    secrets_manager=secrets_manager,
                    count=req_count,
                    country=req_country,
                    search_lang=req_lang,
                    safesearch=req_safesearch
                )
                
                if search_result.get("error"):
                    errors.append(f"Query '{search_query}': {search_result['error']}")
                    continue
                
                # Convert results to preview format and sanitize external content
                results = search_result.get("results", [])
                for result in results:
                    # Sanitize title and description (snippet) to prevent prompt injection
                    # Use a task_id that includes the search query for better traceability
                    task_id = f"search_{i+1}_{search_query[:50]}"  # Limit length for logging
                    
                    title = result.get("title", "")
                    description = result.get("description", "")
                    
                    # Sanitize title and description
                    sanitized_title = await sanitize_external_content(
                        content=title,
                        content_type="text",
                        task_id=f"{task_id}_title",
                        secrets_manager=secrets_manager
                    )
                    sanitized_snippet = await sanitize_external_content(
                        content=description,
                        content_type="text",
                        task_id=f"{task_id}_snippet",
                        secrets_manager=secrets_manager
                    )
                    
                    # Skip result if title was blocked (high risk)
                    if not sanitized_title:
                        logger.warning(f"Search result title blocked due to prompt injection risk: {result.get('url', 'unknown')}")
                        continue
                    
                    preview = {
                        "type": "search_result",
                        "title": sanitized_title,
                        "url": result.get("url", ""),
                        "snippet": sanitized_snippet,  # Use sanitized snippet (may be empty if blocked)
                        "hash": self._generate_result_hash(result.get("url", ""))
                    }
                    all_previews.append(preview)
                
                logger.info(f"Search {i+1}/{len(search_requests)} completed: {len(results)} results for '{search_query}'")
                
            except Exception as e:
                error_msg = f"Query '{search_query}': {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
        
        # Generate follow-up suggestions
        suggestions = []
        if len(all_previews) > 0:
            suggestions = [
                "Search more in depth",
                "Create a PDF report",
                "Get more recent results"
            ]
        
        # Build response
        response = SearchResponse(
            previews=all_previews,
            suggestions_follow_up_requests=suggestions if suggestions else None
        )
        
        # Add error message if there were errors (but still return results if any)
        if errors:
            response.error = "; ".join(errors)
            logger.warning(f"Search completed with {len(errors)} error(s): {response.error}")
        
        logger.info(f"Search skill execution completed: {len(all_previews)} total results, {len(errors)} errors")
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

