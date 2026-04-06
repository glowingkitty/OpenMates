# backend/apps/nutrition/skills/search_recipes.py
#
# Search Recipes skill for the nutrition app.
#
# Searches REWE Online (rewe.de/rezepte/) for recipes matching category filters.
# Uses the free REWE recipe filter API for discovery, then fetches full recipe
# details via Firecrawl JSON extraction (Cloudflare-protected pages).
#
# Data flow:
#   1. LLM calls skill with requests=[{filters: ["vegetarisch", "pasta"], max_results: 5}]
#   2. Skill queries /api/recipe-filter/graphql (free, no auth) to get matching UIDs
#   3. For each recipe: check Dragonfly cache → Directus cache → Firecrawl scrape
#   4. Results sanitized via sanitize_long_text_fields_in_payload (prompt injection defense)
#   5. Grouped results returned as SearchRecipesResponse
#
# Pricing: 50 credits per search (per_unit) — covers Firecrawl cost (~5 credits/page
# on growth plan × 5 results = ~50 raw credits with 3x markup). Cached results are
# near-free, so this price is profitable at steady state.
#
# See: backend/apps/nutrition/providers/rewe_recipe_provider.py

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.nutrition.providers.rewe_recipe_provider import (
    FILTER_TAGS,
    fetch_recipe_details,
    search_recipes_by_filter,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchRecipesRequestItem(BaseModel):
    """A single recipe search request."""

    filters: List[str] = Field(
        description=(
            "List of filter tags to narrow recipes. Available filters: "
            "Diet: fleisch, fisch, vegetarisch, vegan. "
            "Ingredient: nudeln/pasta, kartoffeln, reis, gemuese, kuerbis. "
            "Effort: einfach, mittel, schwer. "
            "Meal: vorspeise, hauptspeise, dessert, beilagen, fruehstueck, "
            "suppen, auflauf, snacks, getraenke. "
            "Diet form: laktosefrei, low-carb, glutenfrei, paleo, wenig-zucker, clean-eating. "
            "Baking: kuchen, torten, brot, muffins, cupcakes, plaetzchen. "
            "Occasion: fruehling, grillen, picknick, kindergerichte, geburtstag, guenstig, party."
        ),
    )
    max_results: int = Field(
        default=6,
        description="Maximum number of recipes to return with full details (1-10, default 6).",
    )
    page: int = Field(
        default=1,
        description="Page number for pagination (1-indexed, 36 results per API page).",
    )


class SearchRecipesRequest(BaseModel):
    """
    Incoming request payload for the search_recipes skill.

    Follows the standard OpenMates 'requests' array convention.
    """

    requests: List[SearchRecipesRequestItem] = Field(
        description=(
            "Array of recipe search requests. Each request contains 'filters' "
            "(list of category tags like 'vegetarisch', 'pasta', 'glutenfrei') "
            "and optionally 'max_results' (1-10)."
        ),
    )


class SearchRecipesResponse(BaseModel):
    """Response payload for the search_recipes skill."""

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="REWE")
    total_available: Optional[int] = None
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "uid",
            "image_url",
            "search_rank",
            "from_cache",
        ],
    )


# ---------------------------------------------------------------------------
# SearchRecipesSkill
# ---------------------------------------------------------------------------


class SearchRecipesSkill(BaseSkill):
    """
    Skill that searches REWE Online for recipes matching dietary and category filters.

    Accepts a 'requests' array where each request contains:
    - filters: List of category tags (required), e.g. ["vegetarisch", "pasta"]
    - max_results: Maximum recipes with full details (1-10, default 5)
    - page: Page number for pagination (default 1)

    Returns recipes with full details including:
    - title, description, image_url, recipe_url
    - prep_time, cook_time, total_time, difficulty, servings
    - rating, rating_count, ernaehrwert_score
    - ingredients[] (amount, unit, name)
    - instructions[] (step, text)
    - nutrition (calories, protein, fat, carbs per serving)
    - dietary_tags[], categories[]

    Uses the free REWE filter API for discovery and Firecrawl for detail extraction.
    Results are cached in Directus (persistent) + Dragonfly (hot) for 30 days.
    """

    FOLLOW_UP_SUGGESTIONS = [
        "Show me only vegetarian options",
        "Find a quicker recipe under 30 minutes",
        "What are the ingredients for the first recipe?",
        "Find a similar recipe that is gluten-free",
        "Show recipes with fewer calories",
    ]

    AVAILABLE_FILTERS = sorted(FILTER_TAGS.keys())

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

        1. Obtain SecretsManager for Firecrawl API key
        2. Validate requests (requires 'filters' field)
        3. For each request: query filter API → fetch details → sanitize
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

        # 2. Validate requests
        validated_requests, validation_error = self._validate_requests_array(
            requests=requests,
            required_field="filters",
            field_display_name="filters",
            empty_error_message="No recipe search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchRecipesResponse(results=[], error=validation_error)
        if not validated_requests:
            return SearchRecipesResponse(
                results=[], error="No valid requests to process",
            )

        # 3. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchRecipesSkill",
            logger=logger,
            secrets_manager=secrets_manager,
            cache_service=cache_service,
            directus_service=directus_service,
        )

        # 4. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=validated_requests,
            logger=logger,
        )

        # Calculate total available from first request
        total_available = None
        if all_results:
            for _, results_list, _, extra in (
                r if len(r) == 4 else (*r, {}) for r in all_results
            ):
                if isinstance(extra, dict) and "total" in extra:
                    total_available = extra["total"]
                    break

        # 5. Build response
        return self._build_response_with_errors(
            response_class=SearchRecipesResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="REWE",
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
            req: Request dict with 'filters', optional 'max_results', 'page'.
            request_id: Unique ID for result grouping.
            **kwargs: Must include 'secrets_manager', optionally 'cache_service',
                      'directus_service'.

        Returns:
            Tuple of (request_id, results_list, error_string_or_none).
        """
        secrets_manager = kwargs.get("secrets_manager")
        cache_service = kwargs.get("cache_service")
        directus_service = kwargs.get("directus_service")

        # Extract parameters
        filters = req.get("filters", [])
        if isinstance(filters, str):
            filters = [f.strip() for f in filters.split(",") if f.strip()]
        max_results = min(10, max(1, int(req.get("max_results", 6))))
        page = max(1, int(req.get("page", 1)))

        if not filters:
            return (request_id, [], "Missing 'filters' in request — provide at least one filter tag")

        try:
            # Step 1: Search via free filter API
            recipe_stubs, total = await search_recipes_by_filter(
                filters=filters,
                page=page,
                max_results=max_results,
            )

            if not recipe_stubs:
                return (request_id, [], None)

            # Step 2: Fetch full details (from cache or Firecrawl)
            detailed_recipes = await fetch_recipe_details(
                recipes=recipe_stubs,
                secrets_manager=secrets_manager,
                cache_service=cache_service,
                directus_service=directus_service,
                max_results=max_results,
            )

            # Step 3: Convert to result dicts
            results: List[Dict[str, Any]] = []
            for recipe in detailed_recipes:
                result = recipe.to_result_dict()
                result["total_available"] = total
                results.append(result)

            logger.info(
                "Recipe search filters=%r → %d recipes (total=%d, %d cached)",
                filters, len(results), total,
                sum(1 for r in detailed_recipes if r.from_cache),
            )

            return (request_id, results, None)

        except Exception as e:
            logger.error(
                "Recipe search failed filters=%r: %s",
                filters, e, exc_info=True,
            )
            return (request_id, [], f"Recipe search failed: {e}")
