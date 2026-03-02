# backend/apps/events/skills/search_skill.py
#
# Events search skill implementation.
#
# Searches for public events (meetups, conferences, hackathons, workshops, etc.)
# using the Meetup provider. The skill is designed to be extensible — additional
# providers (Luma, Eventbrite, Resident Advisor) can be added later.
#
# Architecture:
#   - Direct async execution in the app-events container (no Celery task dispatch)
#   - Each request in the 'requests' array is processed independently
#   - Multiple requests are processed in parallel via asyncio.gather
#
# Pricing: 5 credits per request
#   Cost basis: Meetup GraphQL response ~200 KB via Webshare proxy (~$0.00002/request)
#   The 5-credit price covers proxy cost + compute overhead with comfortable margin.
#
# Provider: Meetup.com internal GraphQL endpoint (gql2)
#   - No API key required — endpoint is publicly accessible
#   - Explicit lat/lon sent in filter — no geo-IP ambiguity
#   - Event description returned inline — zero extra requests needed

import logging
import os
import yaml
from typing import Any, Dict, List, Optional, Tuple

from celery import Celery  # For type hinting only
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.events.providers import meetup as meetup_provider
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models (auto-discovered by apps_api.py for OpenAPI documentation)
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    """
    Request model for event search skill.

    Always uses 'requests' array format for consistency and parallel processing.
    Each request specifies its own parameters; defaults are defined in tool_schema.
    """

    requests: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Array of search request objects. Each object must contain 'query' "
            "and 'location' (or 'lat'/'lon'). Optional parameters: start_date, "
            "end_date, event_type, radius_miles, count."
        ),
    )


class SearchResponse(BaseModel):
    """Response model for event search skill."""

    # Results grouped by request ID. Each entry: {'id': ..., 'results': [...]}
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of request results. Each entry contains 'id' (matching the "
            "request id) and 'results' array with event dicts."
        ),
    )
    provider: str = Field(
        default="Meetup",
        description="The event provider used.",
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on search results.",
    )
    error: Optional[str] = Field(None, description="Error message if the skill failed.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "description",   # Full event description (1–5 KB) — too large for LLM context
            "image_url",     # Image URL — not useful for LLM reasoning
        ],
        description=(
            "Fields excluded from LLM inference to reduce token usage. "
            "Preserved in chat history for UI rendering."
        ),
    )


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class SearchSkill(BaseSkill):
    """
    Events search skill — finds public events using the Meetup provider.

    Supports multiple parallel search requests via the 'requests' array pattern.
    Each request can specify its own location, date range, and event type filter.

    Execution model: direct async in app-events FastAPI container.
    No Celery dispatch — search completes in ~0.5–3s, well within sync timeout.
    """

    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialise SearchSkill.

        Args:
            app:                        BaseApp instance (required by BaseSkill)
            app_id:                     App identifier ('events')
            skill_id:                   Skill identifier ('search')
            skill_name:                 Display name for the skill
            skill_description:          Description of what the skill does
            stage:                      Deployment stage ('development' / 'production')
            full_model_reference:       Unused for this skill (no LLM calls)
            pricing_config:             Pricing configuration (5 credits per request)
            celery_producer:            Unused for this skill (direct async execution)
            skill_operational_defaults: Optional per-skill config from app.yml
        """
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )

        if skill_operational_defaults:
            logger.debug(
                "SearchSkill '%s' received operational_defaults: %s",
                self.skill_name,
                skill_operational_defaults,
            )

        # Load follow-up suggestion strings from app.yml
        self.suggestions_follow_up_requests: List[str] = []
        self._load_suggestions_from_app_yml()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_suggestions_from_app_yml(self) -> None:
        """Load follow-up suggestion strings from the app.yml file."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            app_yml_path = os.path.join(os.path.dirname(current_dir), "app.yml")

            if not os.path.exists(app_yml_path):
                logger.error(
                    "app.yml not found at %s — suggestions_follow_up_requests will be empty",
                    app_yml_path,
                )
                return

            with open(app_yml_path, "r", encoding="utf-8") as fh:
                config = yaml.safe_load(fh)

            for skill in (config or {}).get("skills", []):
                if skill.get("id", "").strip() == "search":
                    suggestions = skill.get("suggestions_follow_up_requests", [])
                    if isinstance(suggestions, list):
                        self.suggestions_follow_up_requests = [str(s) for s in suggestions]
                        logger.debug(
                            "Loaded %d follow-up suggestions from app.yml",
                            len(self.suggestions_follow_up_requests),
                        )
                    return

            logger.warning(
                "Search skill not found in app.yml — suggestions_follow_up_requests will be empty"
            )

        except Exception as exc:
            logger.error(
                "Error loading follow-up suggestions from app.yml: %s",
                exc,
                exc_info=True,
            )

    async def _process_single_search_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,  # noqa: ARG002 — required by BaseSkill helper signature
        proxy_url: Optional[str] = None,
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str], int]:
        """
        Process a single event search request.

        Resolves the location (using built-in lookup or Meetup geocoder),
        calls the Meetup provider, and returns normalised event dicts.

        Args:
            req:             Request dict with query, location/lat/lon, and optional params
            request_id:      ID for matching this request in the grouped response
            secrets_manager: Injected by BaseSkill helper (required by base class pattern)
            proxy_url:       Optional Webshare rotating residential proxy URL.
                             Passed through to meetup_provider.search_events_async().

        Returns:
            Tuple of (request_id, results_list, error_or_None, total_available)
            where total_available is the total count of matching events on Meetup
            (may exceed the returned list if count < totalCount).
        """
        query = req.get("query") or req.get("q")
        if not query:
            return (request_id, [], "Missing 'query' parameter", 0)

        # --- Resolve location ---
        lat: Optional[float] = req.get("lat")
        lon: Optional[float] = req.get("lon")
        city: str = ""
        country: str = ""

        if lat is not None and lon is not None:
            # Explicit coordinates take priority.
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError) as exc:
                return (request_id, [], f"Invalid lat/lon values: {exc}", 0)
        else:
            location_str = req.get("location", "").strip()
            if not location_str:
                return (
                    request_id,
                    [],
                    "Missing 'location' parameter. Provide a city name or explicit lat/lon.",
                    0,
                )
            try:
                lat, lon, city, country = meetup_provider.resolve_location(location_str)
            except ValueError as exc:
                return (request_id, [], f"Location resolution failed: {exc}", 0)

        # --- Optional parameters ---
        start_date: Optional[str] = req.get("start_date")
        end_date: Optional[str] = req.get("end_date")
        event_type: Optional[str] = req.get("event_type")
        radius_miles: float = float(req.get("radius_miles", 25.0))
        count: int = int(req.get("count", 10))

        # Validate event_type
        if event_type and event_type not in ("PHYSICAL", "ONLINE"):
            logger.warning(
                "Invalid event_type %r for request %s — ignoring",
                event_type,
                request_id,
            )
            event_type = None

        logger.debug(
            "Processing event search (id=%s): query=%r lat=%.4f lon=%.4f count=%d",
            request_id,
            query,
            lat,
            lon,
            count,
        )

        try:
            events, total_available = await meetup_provider.search_events_async(
                keywords=query,
                lat=lat,
                lon=lon,
                city=city,
                country=country,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                radius_miles=radius_miles,
                count=count,
                proxy_url=proxy_url,
            )
        except (RuntimeError, ValueError) as exc:
            error_msg = f"Meetup search failed for query {query!r}: {exc}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg, 0)
        except Exception as exc:
            error_msg = f"Unexpected error searching events for query {query!r}: {exc}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg, 0)

        # Add a 'type' field and content hash for UI rendering consistency
        results: List[Dict[str, Any]] = []
        for event in events:
            result = {"type": "event_result", **event}
            # Generate a stable hash from the event URL (unique per event)
            result["hash"] = self._generate_result_hash(event.get("url") or event.get("id") or "")
            results.append(result)

        logger.info(
            "Event search (id=%s) complete: %d results (totalAvailable=%d) for query=%r location=(%.4f, %.4f)",
            request_id,
            len(results),
            total_available,
            query,
            lat,
            lon,
        )
        return (request_id, results, None, total_available)

    # ------------------------------------------------------------------
    # Public execute() — called by BaseApp/route handler
    # ------------------------------------------------------------------

    async def execute(
        self,
        request: SearchRequest,
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        """
        Execute the events search skill.

        Processes all requests in parallel. Each request is independently resolved,
        searched, and normalised before being returned in the grouped response format.

        Args:
            request:         SearchRequest Pydantic model (validated by FastAPI)
            secrets_manager: Injected by app (not required for this skill — no secrets)

        Returns:
            SearchResponse with grouped results and optional follow-up suggestions
        """
        # Get or create SecretsManager via BaseSkill helper (even if unused here —
        # required to satisfy the helper signature and future-proof for rate limiting).
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchSkill",
            error_response_factory=lambda msg: SearchResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        # Extract and validate the requests array
        requests_list = request.requests
        validated_requests, error = self._validate_requests_array(
            requests=requests_list,
            required_field="query",
            field_display_name="query",
            empty_error_message=(
                "No search requests provided. 'requests' array must contain at "
                "least one request with 'query' and 'location' (or 'lat'/'lon')."
            ),
            logger=logger,
        )
        if error:
            return SearchResponse(results=[], error=error)

        # Load Webshare rotating residential proxy credentials from Vault.
        # This distributes Meetup requests across different IPs, preventing
        # server-side rate limiting and IP bans from Meetup's CDN.
        proxy_url: Optional[str] = None
        if secrets_manager:
            try:
                ws_username = await secrets_manager.get_secret(
                    secret_path="kv/data/providers/webshare",
                    secret_key="proxy_username",
                )
                ws_password = await secrets_manager.get_secret(
                    secret_path="kv/data/providers/webshare",
                    secret_key="proxy_password",
                )
                if ws_username and ws_password:
                    # Webshare rotating residential proxies require the "-rotate" suffix
                    # appended to the username (e.g. "user-rotate:pass@p.webshare.io:80/").
                    # Without "-rotate" the proxy returns 407 Proxy Authentication Required
                    # even when credentials are correct.  This format is documented by
                    # WebshareProxyConfig in youtube-transcript-api and confirmed by Webshare.
                    proxy_url = f"http://{ws_username}-rotate:{ws_password}@p.webshare.io:80/"
                    logger.debug("[events:search] Using Webshare rotating proxy for Meetup requests")
            except Exception as exc:
                logger.warning(
                    "[events:search] Could not load proxy credentials: %s. "
                    "Proceeding without proxy.",
                    exc,
                )

        # Process all requests in parallel
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_search_request,
            logger=logger,
            secrets_manager=secrets_manager,
            proxy_url=proxy_url,
        )

        # Group by request ID — handle 4-tuples (request_id, items, error, total_available).
        # The base helper expects 3-tuples, so we process manually here to preserve total_available.
        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        request_order = {req.get("id"): i for i, req in enumerate(validated_requests or [])}

        for result in results:
            if isinstance(result, Exception):
                error_msg = f"Unexpected error processing request: {str(result)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue

            # 4-tuple: (request_id, items, error, total_available)
            request_id, items, error, total_available = result

            if error:
                errors.append(error)
                grouped_results.append({
                    "id": request_id,
                    "results": [],
                    "error": error,
                    "total_available": 0,
                })
            else:
                grouped_results.append({
                    "id": request_id,
                    "results": items,
                    "total_available": total_available,
                })

        grouped_results.sort(key=lambda x: request_order.get(x["id"], 999))

        # Build final response
        response = self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Meetup",
            suggestions=self.suggestions_follow_up_requests,
            logger=logger,
        )

        return response
