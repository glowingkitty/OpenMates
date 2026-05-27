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
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from backend.apps.ai.processing.external_result_sanitizer import sanitize_long_text_fields_in_payload
from backend.apps.base_skill import BaseSkill
from backend.apps.shopping.providers.amazon_provider import (
    search_products as amazon_search,
)
from backend.apps.shopping.providers.amazon_provider import infer_country_from_locale
from backend.apps.shopping.providers.rewe_provider import search_products as rewe_search
from backend.apps.shopping.providers.stoffe_provider import search_products as stoffe_search

logger = logging.getLogger(__name__)


ShoppingProvider = Literal["REWE", "Amazon", "Stoffe.de"]
ShoppingCategory = Literal[
    "grocery",
    "fabrics",
    "sewing_supplies",
    "patterns",
    "general_marketplace",
    "electronics",
    "home",
    "fashion",
    "beauty",
    "books",
    "sports",
    "toys",
    "automotive",
    "health",
    "music",
    "movies",
    "tools",
    "office",
    "pet_supplies",
    "video_games",
    "baby",
]


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchProductsRequestItem(BaseModel):
    """A single product search request."""

    query: str = Field(
        description="Search query (e.g. 'bio joghurt', 'coffee grinder', 'wireless mouse')."
    )
    provider: Optional[ShoppingProvider] = Field(
        default=None,
        description="Product provider: 'REWE', 'Amazon', or 'Stoffe.de'. Inferred from category if omitted.",
    )
    category: Optional[ShoppingCategory] = Field(
        default=None,
        description=(
            "Product category used for provider routing and compatibility validation. "
            "Use 'grocery' for supermarket food/household products, 'fabrics' for fabric by the meter, "
            "'sewing_supplies' for needles/thread/zippers/buttons, 'patterns' for sewing patterns, "
            "or an Amazon marketplace category such as 'electronics', 'home', 'fashion', 'beauty', "
            "'books', 'sports', 'toys', 'automotive', 'health', 'music', 'movies', 'tools', "
            "'office', 'pet_supplies', 'video_games', or 'baby'."
        ),
    )
    country: Optional[str] = Field(
        default=None,
        description=(
            "Optional ISO 3166-1 alpha-2 destination country code (e.g. 'DE', 'AT', 'US'). "
            "Used for provider routing: REWE is Germany-only, Stoffe.de ships to selected European countries, "
            "and Amazon is used for other countries."
        ),
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of products to return (1-20, default 10).",
    )
    sort: str = Field(
        default="relevance",
        description="Sort order: 'relevance', 'price_asc', 'price_desc', 'new' (REWE), "
        "'review_rank', 'newest', 'best_sellers' (Amazon).",
    )
    service_type: Optional[str] = Field(
        default=None,
        description="REWE-only fulfilment type: 'DELIVERY' (home delivery, default) or 'CLICK_AND_COLLECT'.",
    )


class SearchProductsRequest(BaseModel):
    """
    Incoming request payload for the search_products skill.

    Follows the standard OpenMates 'requests' array convention: every skill
    call can contain multiple independent search requests that are processed
    in parallel.
    """

    requests: List[SearchProductsRequestItem] = Field(
        description=(
            "Array of product search request objects. Each object requires "
            "a 'query' field (e.g. 'bio joghurt') and optionally "
            "'provider', 'category', 'country', 'max_results', 'sort', and provider-specific filters."
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
    providers: List[str] = Field(
        default_factory=list,
        description="Providers selected for the search request.",
    )
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
    Skill that searches supported shopping providers for products with live pricing.

    Accepts a 'requests' array where each request contains:
    - query: Search term (required), e.g. "bio joghurt", "pasta barilla"
    - provider: "REWE" | "Amazon" | "Stoffe.de" (default inferred from category/country, else REWE)
    - category: enum used to route omitted providers and reject incompatible combinations
    - country: ISO 3166-1 alpha-2 destination country for provider availability and Amazon localization
    - max_results: Maximum products per search (1–20, default 10)
    - sort: Provider-specific sort order
      - REWE: "relevance" | "price_asc" | "price_desc" | "new"
      - Amazon: "relevance" | "price_asc" | "price_desc" | "review_rank" | "newest" | "best_sellers"
    - service_type: REWE only — "DELIVERY" | "CLICK_AND_COLLECT" (default: "DELIVERY")
    - department: Amazon only category filter (e.g. "electronics", "home")
    - min_price/max_price: Amazon only client-side price filters

    Returns product results grouped by request ID. Each product includes:
    - title, brand, category_path
    - price_cents (current price in euro-cents, requires auth cookie)
    - was_price_cents (if on sale), grammage, deposit_cents
    - price_eur (formatted price string, e.g. "1,39 €")
    - purchase_url, image_url
    - attributes: is_organic, is_vegan, is_vegetarian, etc.

    REWE pricing requires an active session stored in Vault (cookie pool).
    Amazon uses SerpAPI, and Stoffe.de uses its public storefront API.
    """

    FOLLOW_UP_SUGGESTIONS = [
        "Filter for organic products only",
        "Show the cheapest option",
        "Find similar products at a lower price",
        "Add to shopping list",
    ]

    DEFAULT_PROVIDER = "REWE"
    AMAZON_PROVIDER = "AMAZON"
    REWE_PROVIDER = "REWE"
    STOFFE_PROVIDER = "STOFFE.DE"
    REWE_SUPPORTED_COUNTRIES = {"DE"}
    STOFFE_SUPPORTED_COUNTRIES = {
        "AT",
        "BE",
        "BG",
        "CH",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LV",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }

    CATEGORY_DEFAULT_PROVIDERS = {
        "grocery": REWE_PROVIDER,
        "fabrics": STOFFE_PROVIDER,
        "sewing_supplies": STOFFE_PROVIDER,
        "patterns": STOFFE_PROVIDER,
        "general_marketplace": AMAZON_PROVIDER,
        "electronics": AMAZON_PROVIDER,
        "home": AMAZON_PROVIDER,
        "fashion": AMAZON_PROVIDER,
        "beauty": AMAZON_PROVIDER,
        "books": AMAZON_PROVIDER,
        "sports": AMAZON_PROVIDER,
        "toys": AMAZON_PROVIDER,
        "automotive": AMAZON_PROVIDER,
        "health": AMAZON_PROVIDER,
        "music": AMAZON_PROVIDER,
        "movies": AMAZON_PROVIDER,
        "tools": AMAZON_PROVIDER,
        "office": AMAZON_PROVIDER,
        "pet_supplies": AMAZON_PROVIDER,
        "video_games": AMAZON_PROVIDER,
        "baby": AMAZON_PROVIDER,
    }
    CATEGORY_ALLOWED_PROVIDERS = {
        "grocery": {REWE_PROVIDER, AMAZON_PROVIDER},
        "fabrics": {STOFFE_PROVIDER, AMAZON_PROVIDER},
        "sewing_supplies": {STOFFE_PROVIDER, AMAZON_PROVIDER},
        "patterns": {STOFFE_PROVIDER, AMAZON_PROVIDER},
        "general_marketplace": {AMAZON_PROVIDER},
        "electronics": {AMAZON_PROVIDER},
        "home": {AMAZON_PROVIDER},
        "fashion": {AMAZON_PROVIDER},
        "beauty": {AMAZON_PROVIDER},
        "books": {AMAZON_PROVIDER},
        "sports": {AMAZON_PROVIDER},
        "toys": {AMAZON_PROVIDER},
        "automotive": {AMAZON_PROVIDER},
        "health": {AMAZON_PROVIDER},
        "music": {AMAZON_PROVIDER},
        "movies": {AMAZON_PROVIDER},
        "tools": {AMAZON_PROVIDER},
        "office": {AMAZON_PROVIDER},
        "pet_supplies": {AMAZON_PROVIDER},
        "video_games": {AMAZON_PROVIDER},
        "baby": {AMAZON_PROVIDER},
    }

    PROVIDER_DISPLAY_NAMES = {
        REWE_PROVIDER: "REWE",
        AMAZON_PROVIDER: "Amazon",
        STOFFE_PROVIDER: "Stoffe.de",
    }

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve the shopping provider before network search starts."""
        provider, provider_error = cls._resolve_provider(
            request.get("provider"),
            cls._normalize_category(request.get("category")),
            cls._normalize_country(request.get("country")),
        )
        if provider_error:
            return {}

        display_provider = cls.PROVIDER_DISPLAY_NAMES.get(provider, provider)
        return {
            "provider": display_provider,
            "providers": [display_provider],
        }

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
            cache_service=kwargs.get("cache_service"),
        )

        # 4. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=validated_requests,
            logger=logger,
        )

        provider_values = {
            self._resolve_provider(
                req.get("provider"),
                self._normalize_category(req.get("category")),
                self._normalize_country(req.get("country")),
            )[0]
            for req in validated_requests
        }
        response_provider = (
            provider_values.pop() if len(provider_values) == 1 else "MULTI"
        )
        selected_providers = [
            self.PROVIDER_DISPLAY_NAMES.get(provider, provider)
            for provider in sorted(provider_values or {response_provider})
            if provider != "MULTI"
        ]

        # 5. Build and return response
        return self._build_response_with_errors(
            response_class=SearchProductsResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider=(
                self.PROVIDER_DISPLAY_NAMES.get(response_provider, response_provider)
            ),
            providers=selected_providers,
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
        category = self._normalize_category(req.get("category"))
        country: Optional[str] = self._normalize_country(req.get("country"))
        provider, provider_error = self._resolve_provider(
            req.get("provider"),
            category,
            country,
        )
        if provider_error:
            return (request_id, [], provider_error)
        max_results: int = int(req.get("max_results", 10))
        sort: str = req.get("sort", "relevance")
        # Use "or" to handle None from Pydantic model_dump() — prevents None reaching rewe_search()
        service_type: str = req.get("service_type") or "DELIVERY"
        department: Optional[str] = req.get("department")
        min_price_raw = req.get("min_price")
        max_price_raw = req.get("max_price")
        min_price: Optional[float] = (
            float(min_price_raw) if min_price_raw is not None else None
        )
        max_price: Optional[float] = (
            float(max_price_raw) if max_price_raw is not None else None
        )

        if not query:
            return (request_id, [], "Missing 'query' in request")

        # Clamp max_results to sensible range
        max_results = max(1, min(20, max_results))

        try:
            if provider == self.REWE_PROVIDER:
                products, pagination = await rewe_search(
                    query=query,
                    max_results=max_results,
                    sort=sort,
                    service_type=service_type,
                    secrets_manager=secrets_manager,
                )
            elif provider == self.AMAZON_PROVIDER:
                amazon_sort = "newest" if sort == "new" else sort
                locale_hint = (
                    kwargs.get("user_locale")
                    or kwargs.get("user_language")
                    or kwargs.get("language")
                    or kwargs.get("locale")
                )
                resolved_country = country or infer_country_from_locale(locale_hint)
                products, pagination = await amazon_search(
                    query=query,
                    max_results=max_results,
                    sort=amazon_sort,
                    country=resolved_country,
                    department=department,
                    min_price=min_price,
                    max_price=max_price,
                    locale_hint=locale_hint,
                    secrets_manager=secrets_manager,
                )
            elif provider == self.STOFFE_PROVIDER:
                products, pagination = await stoffe_search(
                    query=query,
                    max_results=max_results,
                    sort=sort,
                )
            else:
                return (
                    request_id,
                    [],
                    "Invalid provider. Choose 'REWE', 'Amazon', or 'Stoffe.de'",
                )
        except ValueError as e:
            logger.error(
                "Shopping search parameter error provider=%s query=%r: %s",
                provider,
                query,
                e,
            )
            return (request_id, [], str(e))
        except Exception as e:
            logger.error(
                "Shopping search failed provider=%s query=%r: %s",
                provider,
                query,
                e,
                exc_info=True,
            )
            return (request_id, [], f"{provider.title()} search failed: {e}")

        # Convert REWEProduct objects to result dicts
        results: List[Dict[str, Any]] = []
        for product in products:
            result = product.to_result_dict()
            result["provider"] = provider
            # Include pagination context on each result for frontend reference
            result["total_result_count"] = pagination.get("totalResultCount", 0)
            if provider == self.AMAZON_PROVIDER:
                result["country"] = pagination.get("country")
                result["amazon_domain"] = pagination.get("amazon_domain")
            results.append(result)

        try:
            results = await sanitize_long_text_fields_in_payload(
                payload=results,
                task_id=f"shopping_search_{request_id}",
                secrets_manager=secrets_manager,
                cache_service=kwargs.get("cache_service"),
                min_chars=40,
                max_parallel=3,
            )
        except Exception as sanitize_error:
            logger.error(
                "Shopping content sanitization failed provider=%s query=%r: %s",
                provider,
                query,
                sanitize_error,
                exc_info=True,
            )
            return (request_id, [], "Content sanitization failed")

        logger.info(
            "Shopping search provider=%s query=%r → %d products (total=%d)",
            provider,
            query,
            len(results),
            pagination.get("totalResultCount", 0),
        )

        return (request_id, results, None)

    @classmethod
    def _normalize_category(cls, category: Any) -> Optional[str]:
        if category is None:
            return None
        normalized = str(category).strip().lower().replace("-", "_")
        return normalized or None

    @staticmethod
    def _normalize_country(country: Any) -> Optional[str]:
        if country is None:
            return None
        normalized = str(country).strip().upper()
        if not normalized or not re.match(r"^[A-Z]{2}$", normalized):
            return None
        return normalized

    @classmethod
    def _normalize_provider(cls, provider: Any) -> Optional[str]:
        if provider is None:
            return None
        normalized = str(provider).strip().upper()
        if normalized in {"STOFFE", "STOFFE.DE", "STOFFE_DE"}:
            return cls.STOFFE_PROVIDER
        return normalized or None

    @classmethod
    def _resolve_provider(
        cls,
        provider: Any,
        category: Optional[str],
        country: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        normalized_provider = cls._normalize_provider(provider)

        if category and category not in cls.CATEGORY_DEFAULT_PROVIDERS:
            return (
                normalized_provider or cls.DEFAULT_PROVIDER,
                "Invalid category. Choose one of: %s" % sorted(cls.CATEGORY_DEFAULT_PROVIDERS),
            )

        if normalized_provider:
            resolved_provider = normalized_provider
        elif category:
            resolved_provider = cls.CATEGORY_DEFAULT_PROVIDERS.get(category, cls.DEFAULT_PROVIDER)
            if country and not cls._provider_supports_country(resolved_provider, country):
                resolved_provider = cls.AMAZON_PROVIDER
        else:
            resolved_provider = cls.DEFAULT_PROVIDER
            if country and not cls._provider_supports_country(resolved_provider, country):
                resolved_provider = cls.AMAZON_PROVIDER

        if category and resolved_provider not in cls.CATEGORY_ALLOWED_PROVIDERS[category]:
            return (
                resolved_provider,
                "Invalid provider/category combination: provider '%s' cannot search category '%s'. "
                "Allowed providers: %s"
                % (resolved_provider, category, sorted(cls.CATEGORY_ALLOWED_PROVIDERS[category])),
            )

        if resolved_provider not in {cls.REWE_PROVIDER, cls.AMAZON_PROVIDER, cls.STOFFE_PROVIDER}:
            return resolved_provider, "Invalid provider. Choose 'REWE', 'Amazon', or 'Stoffe.de'"

        if country and not cls._provider_supports_country(resolved_provider, country):
            return (
                resolved_provider,
                "Provider '%s' does not support destination country '%s'. "
                "Use Amazon or omit the provider so it can be inferred."
                % (resolved_provider, country),
            )

        return resolved_provider, None

    @classmethod
    def _provider_supports_country(cls, provider: str, country: str) -> bool:
        if provider == cls.REWE_PROVIDER:
            return country in cls.REWE_SUPPORTED_COUNTRIES
        if provider == cls.STOFFE_PROVIDER:
            return country in cls.STOFFE_SUPPORTED_COUNTRIES
        return True
