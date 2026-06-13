# backend/apps/nutrition/skills/search_recipes.py
#
# Search Recipes skill for the nutrition app.
#
# Searches Edamam Recipe Search v2 for recipes matching free-text queries and
# optional structured nutrition filters. The provider requests instructionLines
# directly, filters recipes without steps, and only paginates when needed.
#
# Data flow:
#   1. LLM calls skill with requests=[{query: "quick vegan pasta", max_results: 5}]
#   2. Skill queries Edamam with explicit fields including instructionLines
#   3. Provider filters missing instructions and normalizes recipe details
#   4. Results sanitized via sanitize_long_text_fields_in_payload
#   5. Grouped results returned as SearchRecipesResponse

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.shared.python_utils.app_skill_helpers import sanitize_long_text_fields_in_payload
from backend.apps.base_skill import BaseSkill
from backend.apps.nutrition.providers.edamam_recipe_provider import (
    DEFAULT_MAX_RESULTS,
    EdamamProviderError,
    search_recipes,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchRecipesRequestItem(BaseModel):
    """A single recipe search request."""

    query: str = Field(
        description=(
            "Free-text recipe query for Edamam Recipe Search, e.g. "
            "'quick vegan pasta', 'gluten-free pancakes', or 'miso salmon'."
        ),
    )
    max_results: int = Field(
        default=DEFAULT_MAX_RESULTS,
        description="Maximum number of recipes to return with full details (1-10, default 6).",
    )
    diet: Optional[List[str]] = Field(default=None, description="Optional Edamam diet labels.")
    health: Optional[List[str]] = Field(default=None, description="Optional Edamam health labels.")
    cuisine_type: Optional[List[str]] = Field(default=None, description="Optional cuisine types.")
    meal_type: Optional[List[str]] = Field(default=None, description="Optional meal types.")
    dish_type: Optional[List[str]] = Field(default=None, description="Optional dish types.")
    excluded: Optional[List[str]] = Field(default=None, description="Ingredients or terms to exclude.")
    time: Optional[str] = Field(default=None, description="Optional total time range, e.g. '1-30'.")
    calories: Optional[str] = Field(default=None, description="Optional calorie range.")
    ingredients: Optional[str] = Field(default=None, description="Optional ingredient count range.")


class SearchRecipesRequest(BaseModel):
    """
    Incoming request payload for the search_recipes skill.

    Follows the standard OpenMates 'requests' array convention.
    """

    requests: List[SearchRecipesRequestItem] = Field(
        description=(
            "Array of recipe search requests. Each request contains a free-text "
            "'query' and optionally Edamam filters like health, diet, time, "
            "calories, cuisine_type, meal_type, dish_type, excluded, and max_results."
        ),
    )


class SearchRecipesResponse(BaseModel):
    """Response payload for the search_recipes skill."""

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="Edamam")
    total_available: Optional[int] = None
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "uid",
            "image_url",
            "images",
            "search_rank",
            "share_url",
        ],
    )


# ---------------------------------------------------------------------------
# SearchRecipesSkill
# ---------------------------------------------------------------------------


class SearchRecipesSkill(BaseSkill):
    """
    Skill that searches Edamam for recipes matching a query and nutrition filters.

    Accepts a 'requests' array where each request contains:
    - query: Free-text recipe query (required), e.g. "quick vegan pasta"
    - max_results: Maximum recipes with full details (1-10, default 6)
    - optional Edamam filters: health, diet, time, cuisine_type, meal_type, etc.

    Returns recipes with full details including:
    - title, source, image_url, recipe_url
    - total_time, servings, ingredients[], instructions[]
    - nutrition totals/per-serving values and Edamam labels
    """

    FOLLOW_UP_SUGGESTIONS = [
        "Show me only vegetarian options",
        "Find a quicker recipe under 30 minutes",
        "What are the ingredients for the first recipe?",
        "Find a similar recipe that is gluten-free",
        "Show recipes with fewer calories",
    ]

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Any = None,
        cache_service: Any = None,
        directus_service: Any = None,
        **kwargs: Any,
    ) -> SearchRecipesResponse:
        """
        Execute the search recipes skill.

        1. Obtain SecretsManager for Edamam credentials
        2. Validate requests (requires 'query' field)
        3. For each request: query Edamam → filter/normalize → sanitize
        4. Group results by request ID
        5. Return SearchRecipesResponse
        """
        # 1. Get or create SecretsManager
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchRecipesSkill",
            error_response_factory=lambda msg: SearchRecipesResponse(
                results=[], error=msg,
            ),
            logger=logger,
        )
        if error_response:
            return error_response

        validated_requests, invalid_grouped_results, validation_errors, validation_error = self._partition_requests_by_required_fields(
            requests=requests,
            required_fields=["query"],
            field_display_names={"query": "query"},
            empty_error_message="No recipe search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchRecipesResponse(results=[], error=validation_error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=SearchRecipesResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider="Edamam",
                suggestions=self.FOLLOW_UP_SUGGESTIONS,
                logger=logger,
                total_available=None,
            )

        # 3. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchRecipesSkill",
            logger=logger,
            secrets_manager=secrets_manager,
        )

        # 4. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=requests,
            logger=logger,
        )
        grouped_results = self._merge_grouped_results_preserving_request_order(
            grouped_results,
            invalid_grouped_results,
            requests,
        )

        # Calculate total available from first request
        total_available = None
        if all_results:
            for result_item in all_results:
                if isinstance(result_item, Exception):
                    continue
                _, results_list, _ = result_item
                for item in results_list:
                    if isinstance(item, dict) and "total_available" in item:
                        total_available = item["total_available"]
                        break
                if total_available is not None:
                    break

        # 5. Build response
        return self._build_response_with_errors(
            response_class=SearchRecipesResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Edamam",
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
            total_available=total_available,
        )

    async def _process_single_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        **kwargs: Any,
    ) -> tuple:
        """
        Process a single recipe search request.

        Args:
            req: Request dict with 'query', optional filters and max_results.
            request_id: Unique ID for result grouping.
            **kwargs: Must include 'secrets_manager', optionally 'cache_service',
                      secrets_manager.

        Returns:
            Tuple of (request_id, results_list, error_string_or_none).
        """
        secrets_manager = kwargs.get("secrets_manager")
        cache_service = kwargs.get("cache_service")
        query = str(req.get("query") or "").strip()
        max_results = min(10, max(1, int(req.get("max_results", DEFAULT_MAX_RESULTS))))

        if not query:
            return (request_id, [], "Missing 'query' in request — provide a recipe search query")

        try:
            search_result = await search_recipes(
                query=query,
                max_results=max_results,
                secrets_manager=secrets_manager,
                diet=req.get("diet"),
                health=req.get("health"),
                cuisine_type=req.get("cuisine_type"),
                meal_type=req.get("meal_type"),
                dish_type=req.get("dish_type"),
                excluded=req.get("excluded"),
                time=req.get("time"),
                calories=req.get("calories"),
                ingredients=req.get("ingredients"),
            )

            if isinstance(search_result, dict):
                results = search_result.get("recipes", [])
                total = search_result.get("total_available")
                raw_hits_seen = search_result.get("raw_hits_seen")
                filtered_out = search_result.get("filtered_out_missing_instructions")
                pages_requested = search_result.get("pages_requested")
            else:
                results = [recipe.to_result_dict() for recipe in search_result.recipes]
                total = search_result.total_available
                raw_hits_seen = search_result.raw_hits_seen
                filtered_out = search_result.filtered_out_missing_instructions
                pages_requested = search_result.pages_requested

            for result in results:
                result["query"] = query
                result["total_available"] = total
                result["raw_hits_seen"] = raw_hits_seen
                result["filtered_out_missing_instructions"] = filtered_out
                result["pages_requested"] = pages_requested

            try:
                results = await sanitize_long_text_fields_in_payload(
                    payload=results,
                    task_id=f"recipe_search_{request_id}",
                    secrets_manager=secrets_manager,
                    cache_service=cache_service,
                    min_chars=40,
                    max_parallel=3,
                )
            except Exception as sanitize_error:
                logger.error(
                    "Recipe content sanitization failed for request %s: %s",
                    request_id,
                    sanitize_error,
                    exc_info=True,
                )
                return (request_id, [], "Content sanitization failed")

            logger.info(
                "Edamam recipe search query=%r → %d recipes (total=%s, raw_hits=%s, filtered_no_steps=%s)",
                query, len(results), total, raw_hits_seen, filtered_out,
            )

            return (request_id, results, None)

        except EdamamProviderError as e:
            logger.warning("Edamam recipe search failed query=%r: %s", query, e)
            return (request_id, [], str(e))

        except Exception as e:
            logger.error(
                "Recipe search failed query=%r: %s",
                query, e, exc_info=True,
            )
            return (request_id, [], f"Recipe search failed: {e}")
