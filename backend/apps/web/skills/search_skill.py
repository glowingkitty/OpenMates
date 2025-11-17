# backend/apps/web/skills/search_skill.py
#
# Web search skill implementation.
# Provides web search functionality using the Brave Search API.
#
# This skill supports multiple search queries in a single request,
# processing them in parallel (up to 9 parallel requests).

import logging
import os
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting
from toon import encode, decode

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
    
    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None
    ) -> SearchResponse:
        """
        Execute web search skill.
        
        Always uses 'requests' array format for consistency and parallel processing support.
        Each request in the array specifies its own parameters with defaults defined in the schema.
        
        Args:
            requests: Array of search request objects. Each object must contain 'query' and can include optional parameters (count, country, search_lang, safesearch).
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
        
        # Validate requests array
        if not requests or len(requests) == 0:
            logger.error("No requests provided to SearchSkill")
            return SearchResponse(
                previews=[],
                error="No search requests provided. 'requests' array must contain at least one request with a 'query' field."
            )
        
        # Validate that all requests have a query
        for i, req in enumerate(requests):
            if not req.get("query"):
                logger.error(f"Request {i+1} in requests array is missing 'query' field")
                return SearchResponse(
                    previews=[],
                    error=f"Request {i+1} is missing required 'query' field"
                )
        
        search_requests = requests
        
        # Process all search requests
        all_previews: List[Dict[str, Any]] = []
        errors: List[str] = []
        
        for i, req in enumerate(search_requests):
            # Extract query and parameters from request
            search_query = req.get("query") or req.get("q")
            if not search_query:
                errors.append(f"Request {i+1}: Missing 'query' parameter")
                continue
            
            # Extract request-specific parameters (with defaults from schema)
            req_count = req.get("count", 10)  # Default from schema
            req_country = req.get("country", "us")  # Default from schema
            req_lang = req.get("search_lang", "en")  # Default from schema
            req_safesearch = req.get("safesearch", "moderate")  # Default from schema
            # Default to web articles only (excludes news, videos, discussions, etc.)
            req_result_filter = req.get("result_filter", "web")  # Default to "web" for web articles
            
            logger.debug(f"Executing search {i+1}/{len(search_requests)}: query='{search_query}', result_filter='{req_result_filter}'")
            
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
                # Enable extra_snippets to get additional context snippets
                search_result = await search_web(
                    query=search_query,
                    secrets_manager=secrets_manager,
                    count=req_count,
                    country=req_country,
                    search_lang=req_lang,
                    safesearch=req_safesearch,
                    extra_snippets=True,  # Enable extra snippets for richer results
                    result_filter=req_result_filter  # Filter to web articles by default
                )
                
                if search_result.get("error"):
                    errors.append(f"Query '{search_query}': {search_result['error']}")
                    continue
                
                # Convert results to preview format and sanitize external content
                # Batch all text content from all results into a single sanitization request using TOON format
                results = search_result.get("results", [])
                task_id = f"search_{i+1}_{search_query[:50]}"  # Limit length for logging
                
                # Build JSON structure with only text fields that need sanitization
                # Exclude: url, page_age, profile.name, meta_url.favicon, thumbnail.original (non-text fields)
                # Include: title, description, extra_snippets (text fields for LLM inference)
                text_data_for_sanitization = {
                    "results": []
                }
                result_metadata = []  # Store non-text metadata for each result
                
                for idx, result in enumerate(results):
                    # Extract text fields that need sanitization
                    title = result.get("title", "").strip()
                    description = result.get("description", "").strip()
                    extra_snippets = result.get("extra_snippets", [])
                    if not isinstance(extra_snippets, list):
                        extra_snippets = []
                    
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
                
                # Convert JSON to TOON format using python-toon package
                if text_data_for_sanitization["results"]:
                    try:
                        toon_text = encode(text_data_for_sanitization)
                        
                        logger.info(f"[{task_id}] Batching {len(results)} search results into single TOON-format sanitization request ({len(toon_text)} chars, ~{len(toon_text)/4:.0f} tokens)")
                        logger.debug(f"[{task_id}] TOON format data:\n{toon_text[:500]}{'...' if len(toon_text) > 500 else ''}")
                        
                        # Sanitize all text content in one request
                        sanitized_toon = await sanitize_external_content(
                            content=toon_text,
                            content_type="text",
                            task_id=task_id,
                            secrets_manager=secrets_manager
                        )
                        
                        # Decode sanitized TOON back to JSON
                        sanitized_data = None
                        if sanitized_toon:
                            try:
                                sanitized_data = decode(sanitized_toon)
                            except Exception as e:
                                logger.error(f"[{task_id}] Failed to decode sanitized TOON: {e}", exc_info=True)
                                # Fallback: use original data if decoding fails
                                sanitized_data = text_data_for_sanitization
                        else:
                            # If sanitization returned empty (blocked), use original data structure but log warning
                            logger.warning(f"[{task_id}] Sanitization returned empty, using original data")
                            sanitized_data = text_data_for_sanitization
                        
                        # Map sanitized content back to results
                        sanitized_results = sanitized_data.get("results", []) if sanitized_data else []
                        
                        for idx, metadata in enumerate(result_metadata):
                            # Get sanitized content, fallback to original if sanitization failed
                            sanitized_result = sanitized_results[idx] if idx < len(sanitized_results) else None
                            
                            if sanitized_result:
                                sanitized_title = sanitized_result.get("title", "").strip()
                                sanitized_description = sanitized_result.get("description", "").strip()
                                sanitized_extra_snippets = sanitized_result.get("extra_snippets", [])
                            else:
                                # Fallback to original if sanitization failed
                                sanitized_title = metadata["original_title"]
                                sanitized_description = metadata["original_description"]
                                sanitized_extra_snippets = metadata["original_extra_snippets"]
                            
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
                            all_previews.append(preview)
                    
                    except Exception as e:
                        logger.error(f"[{task_id}] Error encoding/decoding TOON format: {e}", exc_info=True)
                        # Fallback: process results without sanitization (log warning)
                        logger.warning(f"[{task_id}] Falling back to unsanitized results due to TOON error")
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
                            all_previews.append(preview)
                else:
                    # No text content to sanitize - add results as-is (shouldn't happen but handle it)
                    logger.warning(f"[{task_id}] No text content found in search results to sanitize")
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
                        all_previews.append(preview)
                
                logger.info(f"Search {i+1}/{len(search_requests)} completed: {len(results)} results for '{search_query}'")
                
            except Exception as e:
                error_msg = f"Query '{search_query}': {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
        
        # Use follow-up suggestions loaded from app.yml
        # Only include suggestions if we have results and suggestions are configured
        suggestions = None
        if len(all_previews) > 0 and self.suggestions_follow_up_requests:
            suggestions = self.suggestions_follow_up_requests
        
        # Build response
        response = SearchResponse(
            previews=all_previews,
            suggestions_follow_up_requests=suggestions
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

