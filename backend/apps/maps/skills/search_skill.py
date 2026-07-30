# backend/apps/maps/skills/search_skill.py
#
# Maps search skill implementation.
# Provides place search functionality using the Google Places API (New).
#
# This skill supports multiple search queries in a single request,
# processing them in parallel (up to 5 parallel requests).

import asyncio
import logging
import os
import yaml
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from celery import Celery  # For Celery type hinting

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.google_maps.google_places import search_places
from backend.shared.providers.geoapify.places import (
    GEOAPIFY_SOURCE_LABEL,
    GeoapifyPlacesProvider,
    build_status_enrichment,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.app_skill_helpers import (
    check_rate_limit,
    sanitize_long_text_fields_in_payload,
    wait_for_rate_limit,
)
# RateLimitScheduledException is no longer caught here - it bubbles up to route handler
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

OSM_ENRICHMENT_MODES = {"auto", "disabled", "required"}
DEFAULT_OSM_ENRICHMENT_MODE = "auto"
GEOAPIFY_PROVIDER_NAME = "Geoapify"
GEOAPIFY_COMBINED_PROVIDER_NAME = "Google Maps + Geoapify"
GEOAPIFY_DETAIL_LIMIT = 5
GEOAPIFY_TIMEOUT_SECONDS = 1.2


class MapSearchRequestItem(BaseModel):
    """A single maps/places search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: str = Field(
        description="Text query string to search for places (e.g. 'restaurants in Berlin', 'museums near Times Square')."
    )
    pageSize: int = Field(default=10, description="Number of results to return per request (max 20).")
    languageCode: str = Field(default="en", description="Language code for results (ISO 639-1, e.g. 'en', 'es', 'fr', 'de').")
    locationBias: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional location bias (circle with center+radius, or rectangle viewport).",
    )
    includedType: Optional[str] = Field(
        default=None,
        description="Filter results by place type (e.g. 'restaurant', 'museum', 'hotel').",
    )
    minRating: Optional[float] = Field(
        default=None,
        description="Minimum rating filter (0.0 to 5.0).",
    )
    openNow: Optional[bool] = Field(
        default=None,
        description="If true, only return places that are currently open.",
    )
    includeReviews: Optional[bool] = Field(
        default=None,
        description="If true, include reviews in the results.",
    )
    priceLevels: Optional[List[str]] = Field(
        default=None,
        description="Filter by price level. Array of: 'PRICE_LEVEL_FREE', "
        "'PRICE_LEVEL_INEXPENSIVE', 'PRICE_LEVEL_MODERATE', "
        "'PRICE_LEVEL_EXPENSIVE', 'PRICE_LEVEL_VERY_EXPENSIVE'.",
    )
    osmEnrichment: Optional[str] = Field(
        default=DEFAULT_OSM_ENRICHMENT_MODE,
        description="OSM/Geoapify enrichment mode: 'auto', 'disabled', or 'required'.",
    )
    amenityFilters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional required amenity filters for OSM-backed fields such as airConditioning, internetAccess, wheelchair, toilets, outdoorSeating, diet, or payment.",
    )


class SearchRequest(BaseModel):
    """
    Request model for maps search skill.
    Always uses 'requests' array format for consistency and parallel processing support.
    Each request specifies its own parameters with defaults defined in the tool_schema.
    """
    requests: List[MapSearchRequestItem] = Field(
        ...,
        description="Array of map search request objects. Each object must contain 'query' and can include optional parameters (pageSize, languageCode, locationBias, includedType, minRating, openNow, includeReviews)."
    )


class SearchResponse(BaseModel):
    """Response model for maps search skill."""
    # Results are grouped by request id - each entry contains 'id' and 'results' array
    # This structure allows clients to match responses to original requests without redundant data
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' (matching request id) and 'results' array with actual place search results for that request."
    )
    provider: str = Field(
        default="Google Maps",
        description="The search provider used (e.g., 'Google Maps')"
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
            "place_id",
            "_raw",
            # Price range details - price_level enum is sufficient for LLM understanding
            # price_range contains startPrice/endPrice with currency/units which is redundant
            "price_range"
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
    Maps search skill that uses Google Places API (New) to search for places.
    
    Supports multiple search queries in a single request, processing them in parallel.
    Each query is executed independently and results are combined.
    
    ARCHITECTURE DECISION: Direct Async Execution vs Celery Tasks
    ==============================================================
    
    This skill executes directly in the FastAPI route handler (app-maps container) using
    async/await, rather than dispatching to a Celery task in app-maps-worker. This is an
    intentional architectural decision for the following reasons:
    
    1. **Performance & Latency**
       - Place search is a quick operation (typically 0.5-2 seconds)
       - Direct async execution has ~0ms overhead vs Celery's ~50-200ms overhead
         (task dispatch + queue wait + result retrieval)
       - Users expect immediate results for search queries
    
    2. **Non-Blocking Concurrency**
       - The execute() method uses async/await, making it non-blocking
       - FastAPI's event loop can handle thousands of concurrent requests efficiently
       - During I/O operations (HTTP calls to Google Places API), the
         event loop yields control, allowing other requests to be processed
       - This is NOT blocking - multiple requests are processed concurrently
    
    3. **I/O-Bound Nature**
       - Place search is primarily I/O-bound (network calls, not CPU-intensive)
       - Async I/O is perfectly suited for this use case
       - No CPU-bound work that would benefit from separate worker processes
    
    4. **Simplicity**
       - Direct execution is simpler: no task queue, no polling, no result storage
       - Easier to debug and monitor (logs appear directly in app-maps)
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
    - Place search (quick, I/O-bound)
    - Quick API lookups
    - Simple data transformations
    - Fast external service calls
    
    Current Implementation:
    ----------------------
    - Executes in: app-maps (FastAPI container)
    - Execution model: Direct async execution via async/await
    - Concurrency: Handled by FastAPI's async event loop
    - Blocking: NO - async I/O operations yield control to event loop
    - Scalability: Excellent - FastAPI handles thousands of concurrent requests
    
    Note: Google Places API data is trusted and does not require content sanitization
    (unlike web search results which may contain user-generated content).
    """
    
    def __init__(self,
                 app,  # BaseApp instance - required by BaseSkill
                 app_id: str,
                 skill_id: str,
                 skill_name: str,  # Changed from 'name' to match BaseSkill
                 skill_description: str,  # Changed from 'description' to match BaseSkill
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

    def _group_maps_results_by_request_id(
        self,
        results: List[Any],
        requests: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Group maps results and preserve per-request warning metadata."""

        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []

        for result in results:
            if isinstance(result, Exception):
                error_msg = f"Unexpected error processing request: {str(result)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue

            request_id = result[0]
            items = result[1]
            error = result[2]
            metadata = result[3] if len(result) > 3 and isinstance(result[3], dict) else {}

            group: Dict[str, Any] = {"id": request_id, "results": [] if error else items}
            if error:
                errors.append(error)
                group["error"] = error
            warnings = metadata.get("warnings")
            if warnings:
                group["warnings"] = warnings
            filter_summary = metadata.get("filter_summary")
            if filter_summary:
                group["filter_summary"] = filter_summary
            grouped_results.append(group)

        request_order = {req.get("id"): i for i, req in enumerate(requests)}
        grouped_results.sort(key=lambda x: request_order.get(x["id"], 999))
        return grouped_results, errors

    async def _apply_geoapify_enrichment(
        self,
        *,
        previews: List[Dict[str, Any]],
        req: Dict[str, Any],
        secrets_manager: SecretsManager,
        cache_service: CacheService,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        mode = self._normalize_osm_enrichment_mode(req.get("osmEnrichment"))
        if mode == "disabled" or not previews:
            return previews, {"geoapify_requested": False}

        required_amenities = self._required_amenities_from_filters(req.get("amenityFilters"))
        if mode == "required" and not required_amenities:
            required_amenities = self._required_amenities_from_query(str(req.get("query") or ""))

        try:
            enrichments = await asyncio.wait_for(
                self._enrich_with_geoapify(
                    places=previews,
                    req=req,
                    secrets_manager=secrets_manager,
                    cache_service=cache_service,
                    required_amenities=required_amenities,
                ),
                timeout=GEOAPIFY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            enrichments = [build_status_enrichment("timed_out") for _ in previews]
        except Exception as exc:
            logger.warning("Geoapify enrichment failed for maps search: %s", exc, exc_info=True)
            enrichments = [build_status_enrichment("unavailable") for _ in previews]

        completed_enrichments = self._complete_enrichment_records(enrichments, len(previews))
        enriched_previews: List[Dict[str, Any]] = []
        for preview, enrichment in zip(previews, completed_enrichments):
            enriched_preview = dict(preview)
            enriched_preview["osm_enrichment"] = enrichment
            enriched_previews.append(enriched_preview)

        warnings = self._geoapify_warnings(completed_enrichments)
        metadata: Dict[str, Any] = {"geoapify_requested": True}

        if required_amenities:
            filtered = [
                preview
                for preview in enriched_previews
                if self._enrichment_satisfies_required(
                    preview.get("osm_enrichment", {}),
                    required_amenities,
                )
            ]
            filter_summary = {
                "required": required_amenities,
                "candidate_count": len(previews),
                "verified_count": len(filtered),
                "status": "verified_results" if filtered else "no_verified_results",
            }
            metadata["filter_summary"] = filter_summary
            if not filtered:
                warnings.append(
                    "No Geoapify/OSM-verified matches were found within the enrichment budget; try relaxing the amenity filter."
                )
            enriched_previews = filtered

        if warnings:
            metadata["warnings"] = warnings
        return enriched_previews, metadata

    async def _enrich_with_geoapify(
        self,
        *,
        places: List[Dict[str, Any]],
        req: Dict[str, Any],
        secrets_manager: SecretsManager,
        cache_service: CacheService,
        required_amenities: List[str],
    ) -> List[Dict[str, Any]]:
        """Fetch bounded Geoapify enrichment records for Google Places candidates."""

        provider = GeoapifyPlacesProvider(
            secrets_manager=secrets_manager,
            cache_service=cache_service,
            timeout_seconds=GEOAPIFY_TIMEOUT_SECONDS,
        )
        search_result = await provider.search_places(
            query=str(req.get("query") or ""),
            limit=min(len(places), 20),
            conditions=self._geoapify_conditions_for_required(required_amenities),
        )
        if search_result.status != "ok":
            return [build_status_enrichment(search_result.status) for _ in places]

        if not search_result.places:
            return [build_status_enrichment("no_match") for _ in places]

        detail_limit = min(len(places), len(search_result.places), GEOAPIFY_DETAIL_LIMIT)
        enrichments: List[Dict[str, Any]] = []
        for index in range(detail_limit):
            place_id = self._geoapify_place_id(search_result.places[index])
            if not place_id:
                enrichments.append(build_status_enrichment("no_match"))
                continue
            detail = await provider.get_place_details(place_id=place_id)
            enrichments.append(detail.enrichment)

        while len(enrichments) < len(places):
            enrichments.append(build_status_enrichment("no_match"))
        return enrichments

    def _normalize_osm_enrichment_mode(self, value: Any) -> str:
        mode = str(value or DEFAULT_OSM_ENRICHMENT_MODE).strip().lower()
        return mode if mode in OSM_ENRICHMENT_MODES else DEFAULT_OSM_ENRICHMENT_MODE

    def _required_amenities_from_filters(self, filters: Any) -> List[str]:
        if not isinstance(filters, dict):
            return []
        required: List[str] = []
        for raw_key, raw_value in filters.items():
            value = str(raw_value).strip().lower() if raw_value is not None else ""
            if raw_value is True or value in {"required", "yes", "true"} or value.endswith("_required"):
                required.append(self._canonical_amenity_name(str(raw_key)))
        return list(dict.fromkeys(required))

    def _required_amenities_from_query(self, query: str) -> List[str]:
        lowered = query.lower()
        required: List[str] = []
        if "air conditioning" in lowered or "air-conditioned" in lowered or " ac" in lowered:
            required.append("air_conditioning")
        if "wifi" in lowered or "wi-fi" in lowered or "internet" in lowered:
            required.append("internet_access")
        if "wheelchair" in lowered:
            required.append("wheelchair")
        return required

    def _canonical_amenity_name(self, value: str) -> str:
        aliases = {
            "airConditioning": "air_conditioning",
            "air_conditioning": "air_conditioning",
            "internetAccess": "internet_access",
            "internet_access": "internet_access",
            "wifi": "internet_access",
            "wheelchairAccess": "wheelchair",
            "wheelchair": "wheelchair",
            "outdoorSeating": "outdoor_seating",
            "outdoor_seating": "outdoor_seating",
        }
        if value in aliases:
            return aliases[value]
        normalized = []
        for char in value:
            if char.isupper():
                normalized.append("_")
                normalized.append(char.lower())
            elif char in {"-", " "}:
                normalized.append("_")
            else:
                normalized.append(char)
        return "".join(normalized).strip("_")

    def _geoapify_conditions_for_required(self, required_amenities: List[str]) -> List[str]:
        conditions: List[str] = []
        if "internet_access" in required_amenities:
            conditions.append("internet_access.free")
        if "wheelchair" in required_amenities:
            conditions.append("wheelchair")
        return conditions

    def _geoapify_place_id(self, feature: Dict[str, Any]) -> Optional[str]:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if isinstance(properties, dict):
            place_id = properties.get("place_id") or properties.get("id")
            if place_id:
                return str(place_id)
        feature_id = feature.get("id") if isinstance(feature, dict) else None
        return str(feature_id) if feature_id else None

    def _complete_enrichment_records(
        self,
        enrichments: List[Dict[str, Any]],
        expected_count: int,
    ) -> List[Dict[str, Any]]:
        completed: List[Dict[str, Any]] = []
        for enrichment in enrichments[:expected_count]:
            record = dict(enrichment) if isinstance(enrichment, dict) else {}
            status = record.get("status") or "no_match"
            record.setdefault("provider", GEOAPIFY_PROVIDER_NAME)
            record.setdefault("data_source", GEOAPIFY_SOURCE_LABEL)
            record["status"] = status
            record.setdefault("match", {"cache_hit": False})
            record.setdefault("fields", {})
            completed.append(record)
        while len(completed) < expected_count:
            completed.append(build_status_enrichment("no_match"))
        return completed

    def _geoapify_warnings(self, enrichments: List[Dict[str, Any]]) -> List[str]:
        statuses = {str(enrichment.get("status")) for enrichment in enrichments}
        if statuses == {"timed_out"}:
            return ["Geoapify OSM enrichment timed out; showing Google Places results."]
        if statuses == {"not_configured"}:
            return ["Geoapify OSM enrichment is not configured; showing Google Places results."]
        if "rate_limited" in statuses:
            return ["Geoapify OSM enrichment is rate limited; showing available Google Places results."]
        if "unavailable" in statuses:
            return ["Geoapify OSM enrichment is unavailable; showing Google Places results."]
        return []

    def _enrichment_satisfies_required(
        self,
        enrichment: Dict[str, Any],
        required_amenities: List[str],
    ) -> bool:
        fields = enrichment.get("fields") if isinstance(enrichment, dict) else None
        if not isinstance(fields, dict):
            return False
        for amenity in required_amenities:
            field_record = fields.get(amenity)
            if not self._field_value_is_verified(field_record):
                return False
        return True

    def _field_value_is_verified(self, field_record: Any) -> bool:
        if not isinstance(field_record, dict):
            return False
        value = field_record.get("value")
        if value in (None, False, "", "unknown", "no"):
            return False
        if isinstance(value, dict):
            return any(item not in (None, False, "", "unknown", "no") for item in value.values())
        return True
    
    async def _process_single_search_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
        cache_service: CacheService
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str]]:
        """
        Process a single place search request.
        
        This method handles all the logic for processing one place search request:
        - Parameter extraction and validation
        - Rate limit checking
        - API call to Google Places API
        - Result formatting
        
        Note: Google Places API data is trusted and does not require content sanitization.
        
        Args:
            req: Request dictionary with query and optional parameters
            request_id: The id of this request (for matching in response)
            secrets_manager: SecretsManager instance
            cache_service: CacheService instance for rate limiting
        
        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
            - request_id: The id of the request (for grouping in response)
            - results_list: List of place result previews (empty if error)
            - error_string_or_none: Error message if processing failed, None if successful
        """
        # Extract query and parameters from request
        search_query = req.get("query")
        if not search_query:
            return (request_id, [], "Missing 'query' parameter")
        
        # Extract request-specific parameters (with defaults from schema)
        req_page_size = req.get("pageSize", 20)
        req_language_code = req.get("languageCode", "en")
        req_location_bias = req.get("locationBias")
        req_included_type = req.get("includedType")
        req_min_rating = req.get("minRating")
        # Use "is not None" checks to handle None from Pydantic model_dump() for Optional[bool].
        # "or False" would incorrectly convert an explicit False to False (safe), but we prefer
        # explicit None-awareness for booleans since False is a meaningful value.
        _raw_open_now = req.get("openNow")
        req_open_now = _raw_open_now if _raw_open_now is not None else False
        _raw_include_reviews = req.get("includeReviews")
        req_include_reviews = _raw_include_reviews if _raw_include_reviews is not None else False
        req_price_levels = req.get("priceLevels")
        req_osm_enrichment = self._normalize_osm_enrichment_mode(req.get("osmEnrichment"))
        
        logger.debug(f"Executing place search (id: {request_id}): query='{search_query}', page_size={req_page_size}")
        
        try:
            # Check and enforce rate limits before calling external API
            provider_id = "google_maps"
            skill_id = "search"
            
            # Check rate limit
            is_allowed, retry_after = await check_rate_limit(
                provider_id=provider_id,
                skill_id=skill_id,
                cache_service=cache_service
            )
            
            # If rate limited, wait for the limit to reset
            if not is_allowed:
                logger.info(f"Rate limit hit for place search '{search_query}' (id: {request_id}), waiting for reset...")
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
                                "pageSize": req_page_size,
                                "languageCode": req_language_code,
                                "locationBias": req_location_bias,
                                "includedType": req_included_type,
                                "minRating": req_min_rating,
                                "openNow": req_open_now
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
            
            # Call Google Places API
            search_result = await search_places(
                text_query=search_query,
                secrets_manager=secrets_manager,
                page_size=req_page_size,
                language_code=req_language_code if req_language_code else None,
                location_bias=req_location_bias if req_location_bias else None,
                included_type=req_included_type if req_included_type else None,
                min_rating=req_min_rating if req_min_rating is not None else None,
                open_now=req_open_now if req_open_now else None,
                include_reviews=req_include_reviews,
                price_levels=req_price_levels,
            )
            
            if search_result.get("error"):
                return (request_id, [], f"Query '{search_query}': {search_result['error']}")
            
            # Convert results to preview format
            # Google Places API data is trusted and does not require content sanitization
            places = search_result.get("results", [])
            previews: List[Dict[str, Any]] = []
            
            for place in places:
                # Build preview with place data
                preview = {
                    "type": "place_result",
                    "place_id": place.get("place_id", ""),
                    "name": place.get("name", ""),
                    "formatted_address": place.get("formatted_address", ""),
                    "location": place.get("location"),
                    "types": place.get("types", []),
                    "rating": place.get("rating"),
                    "user_rating_count": place.get("user_rating_count"),
                    "website_uri": place.get("website_uri"),
                    "phone_number": place.get("phone_number"),
                    "price_level": place.get("price_level"),
                    "price_range": place.get("price_range"),
                    "opening_hours": place.get("opening_hours"),
                    "open_now": place.get("open_now"),
                    "next_close_time": place.get("next_close_time"),
                    "business_status": place.get("business_status"),
                    "description": place.get("description"),
                    "photo_url": place.get("photo_url"),
                    "image_url": place.get("image_url") or place.get("photo_url"),
                    "hash": self._generate_result_hash(place.get("place_id", ""))
                }
                # Only include generative_summary if it exists
                generative_summary = place.get("generative_summary")
                if generative_summary:
                    preview["generative_summary"] = generative_summary
                # Only include reviews if they were requested
                reviews = place.get("reviews")
                if reviews:
                    preview["reviews"] = reviews
                previews.append(preview)

            try:
                previews = await sanitize_long_text_fields_in_payload(
                    payload=previews,
                    task_id=f"maps_search_{request_id}",
                    secrets_manager=secrets_manager,
                    cache_service=cache_service,
                )
            except Exception as sanitize_error:
                logger.error(
                    f"Content sanitization failed for maps request {request_id}: {sanitize_error}",
                    exc_info=True,
                )
                return (request_id, [], f"Query '{search_query}': Content sanitization failed")

            previews, metadata = await self._apply_geoapify_enrichment(
                previews=previews,
                req={**req, "osmEnrichment": req_osm_enrichment},
                secrets_manager=secrets_manager,
                cache_service=cache_service,
            )
            
            logger.info(f"Place search (id: {request_id}) completed: {len(previews)} results for '{search_query}'")
            return (request_id, previews, None, metadata)
            
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
        Execute maps search skill.
        
        Always uses 'requests' array format for consistency and parallel processing support.
        Each request in the array specifies its own parameters with defaults defined in the schema.
        
        NOTE: This method executes directly in the FastAPI route handler (not via Celery).
        This is intentional - see class docstring for architecture decision rationale.
        The async/await pattern ensures non-blocking execution and excellent concurrency.
        
        Args:
            requests: Array of search request objects. Each object must contain 'query' and can include optional parameters (pageSize, languageCode, locationBias, includedType, minRating, openNow, includeReviews).
            secrets_manager: SecretsManager instance (injected by app)
        
        Returns:
            SearchResponse with place results and optional follow-up suggestions
        
        Execution Flow:
        --------------
        1. Request received in FastAPI route handler (app-maps container)
        2. This async method is called directly (no Celery dispatch)
        3. I/O operations (Google Places API calls) use await
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
        
        validated_requests, invalid_grouped_results, validation_errors, error = self._partition_requests_by_required_fields(
            requests=requests,
            required_fields=["query"],
            field_display_names={"query": "query"},
            empty_error_message="No search requests provided. 'requests' array must contain at least one request with a 'query' field.",
            logger=logger
        )
        if error:
            return SearchResponse(results=[], error=error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=SearchResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider="Google Maps",
                suggestions=self.suggestions_follow_up_requests,
                logger=logger
            )
        
        # Initialize cache service for rate limiting and demand-cached enrichment.
        cache_service = CacheService()
        
        # Process all search requests in parallel using BaseSkill helper
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_search_request,
            logger=logger,
            secrets_manager=secrets_manager,
            cache_service=cache_service
        )
        
        # Group results by request ID while preserving maps-specific metadata.
        grouped_results, errors = self._group_maps_results_by_request_id(
            results=results,
            requests=requests,
        )
        grouped_results = self._merge_grouped_results_preserving_request_order(
            grouped_results,
            invalid_grouped_results,
            requests,
        )
        
        # Build response with errors using BaseSkill helper
        response_provider = (
            GEOAPIFY_COMBINED_PROVIDER_NAME
            if any(self._normalize_osm_enrichment_mode(req.get("osmEnrichment")) != "disabled" for req in validated_requests)
            else "Google Maps"
        )
        response = self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider=response_provider,
            suggestions=self.suggestions_follow_up_requests,
            logger=logger
        )
        
        return response
    
    # _generate_result_hash is now provided by BaseSkill (can hash any string, including place_id)
