"""
Search Products skill for the shopping app.

Searches the REWE online shop (shop.rewe.de) for products with real-time prices.
Uses the REWEProvider to handle authentication via a Playwright-harvested cookie pool
stored in Vault, and routes all requests through a residential proxy.

The skill follows the standard BaseSkill request/response pattern with the
'requests' array convention used by all OpenMates skills.

Data flow:
  1. LLM calls skill with requests=[{query: "bio joghurt", max_results: 10}]
  2. Skill validates input with _validate_requests_array (requires 'query')
  3. Each request is processed in parallel via _process_requests_in_parallel
  4. For each request: REWEProvider fetches the cookie pool from Vault and
     calls the REWE REST API with auth cookies + residential proxy
  5. Results are grouped by request ID and returned as SearchProductsResponse
  6. Frontend renders products in ShoppingSearchEmbedPreview / Fullscreen

See: backend/apps/shopping/providers/rewe_provider.py for the HTTP layer.
See: docs/architecture/shopping-cookie-pool.md for the cookie harvesting design.
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.shopping.providers.rewe_provider import search_products as rewe_search

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchProductsRequest(BaseModel):
    """
    Incoming request payload for the search_products skill.

    Follows the standard OpenMates 'requests' array convention: every skill
    call can contain multiple independent search requests that are processed
    in parallel.
    """

    requests: List[Dict[str, Any]] = Field(
        description=(
            "Array of product search request objects. Each object requires "
            "a 'query' field (e.g. 'bio joghurt') and optionally "
            "'max_results', 'sort', and 'service_type'."
        )
    )


class SearchProductsResponse(BaseModel):
    """
    Response payload for the search_products skill.

    Follows the standard OpenMates skill response structure with grouped
    results, provider info, follow-up suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="REWE")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "product_id",
            "image_url",
            "category_ids",
            "order_limit",
            "search_rank",
        ]
    )


# ---------------------------------------------------------------------------
# SearchProductsSkill
# ---------------------------------------------------------------------------


class SearchProductsSkill(BaseSkill):
    """
    Skill that searches the REWE online shop for products with live pricing.

    Accepts a 'requests' array where each request contains:
    - query: Search term (required), e.g. "bio joghurt", "pasta barilla"
    - max_results: Maximum products per search (1–20, default 10)
    - sort: Sort order — "relevance" | "price_asc" | "price_desc" | "new"
    - service_type: "DELIVERY" | "CLICK_AND_COLLECT" (default: "DELIVERY")

    Returns product results grouped by request ID. Each product includes:
    - title, brand, category_path
    - price_cents (current price in euro-cents, requires auth cookie)
    - was_price_cents (if on sale), grammage, deposit_cents
    - price_eur (formatted price string, e.g. "1,39 €")
    - purchase_url, image_url
    - attributes: is_organic, is_vegan, is_vegetarian, etc.

    Pricing requires an active REWE session stored in Vault (cookie pool).
    Without cookies, basic product info is returned but prices are None.
    """

    FOLLOW_UP_SUGGESTIONS = [
        "Filter for organic products only",
        "Show the cheapest option",
        "Find similar products at a lower price",
        "Add to shopping list",
    ]

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> SearchProductsResponse:
        """
        Execute the search products skill.

        1. Obtain SecretsManager for Vault cookie pool access
        2. Validate the requests array (requires 'query' field)
        3. Process each request via _process_single_request in parallel
        4. Group results by request ID
        5. Return SearchProductsResponse
        """
        # 1. Get or create SecretsManager (for loading REWE cookies from Vault)
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchProductsSkill",
            error_response_factory=lambda msg: SearchProductsResponse(
                results=[], error=msg
            ),
            logger=logger,
        )
        if error_response:
            return error_response

        # 2. Validate requests array — each must have a 'query' field
        validated_requests, validation_error = self._validate_requests_array(
            requests=requests,
            required_field="query",
            field_display_name="query",
            empty_error_message="No product search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchProductsResponse(results=[], error=validation_error)
        if not validated_requests:
            return SearchProductsResponse(
                results=[], error="No valid requests to process"
            )

        # 3. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchProductsSkill",
            logger=logger,
            secrets_manager=secrets_manager,
        )

        # 4. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=validated_requests,
            logger=logger,
        )

        # 5. Build and return response
        return self._build_response_with_errors(
            response_class=SearchProductsResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="REWE",
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
        )

    async def _process_single_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        **kwargs: Any,
    ) -> tuple:
        """
        Process a single product search request.

        Args:
            req: The request dict (requires 'query', optional 'max_results',
                 'sort', 'service_type').
            request_id: Unique ID for this request (used for result grouping).
            **kwargs: Additional kwargs — must include 'secrets_manager'.

        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
        """
        secrets_manager = kwargs.get("secrets_manager")

        # Extract parameters with defaults
        query: str = req.get("query", "").strip()
        max_results: int = int(req.get("max_results", 10))
        sort: str = req.get("sort", "relevance")
        service_type: str = req.get("service_type", "DELIVERY")

        if not query:
            return (request_id, [], "Missing 'query' in request")

        # Clamp max_results to sensible range
        max_results = max(1, min(20, max_results))

        try:
            products, pagination = await rewe_search(
                query=query,
                max_results=max_results,
                sort=sort,
                service_type=service_type,
                secrets_manager=secrets_manager,
            )
        except ValueError as e:
            logger.error(
                "REWE search parameter error for query=%r: %s", query, e
            )
            return (request_id, [], str(e))
        except Exception as e:
            logger.error(
                "REWE search failed for query=%r: %s", query, e, exc_info=True
            )
            return (request_id, [], f"REWE search failed: {e}")

        # Convert REWEProduct objects to result dicts
        results: List[Dict[str, Any]] = []
        for product in products:
            result = product.to_result_dict()
            # Include pagination context on each result for frontend reference
            result["total_result_count"] = pagination.get("totalResultCount", 0)
            results.append(result)

        logger.info(
            "REWE search query=%r → %d products (total=%d)",
            query,
            len(results),
            pagination.get("totalResultCount", 0),
        )

        return (request_id, results, None)
