"""
Amazon product search provider for the shopping app.

Uses SerpAPI's Amazon engine to fetch product search results across Amazon
marketplaces and normalizes them into the shopping embed's product result shape.

Architecture: provider-only HTTP layer for shopping.search_products.
See docs/apps/shopping.md for app-level shopping architecture.
Tests: N/A (covered by skill-level and end-to-end app tests).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import httpx

from backend.shared.providers.serpapi import SERPAPI_BASE, get_serpapi_key_async

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

MAX_RESULTS_LIMIT = 20
DEFAULT_COUNTRY = "us"
DEFAULT_LANGUAGE = "en_US"
DEFAULT_SORT = "relevance"

COUNTRY_TO_DOMAIN: Dict[str, str] = {
    "us": "amazon.com",
    "uk": "amazon.co.uk",
    "de": "amazon.de",
    "fr": "amazon.fr",
    "it": "amazon.it",
    "es": "amazon.es",
    "ca": "amazon.ca",
    "au": "amazon.com.au",
    "jp": "amazon.co.jp",
    "in": "amazon.in",
    "br": "amazon.com.br",
    "mx": "amazon.com.mx",
    "nl": "amazon.nl",
    "sg": "amazon.sg",
    "se": "amazon.se",
    "pl": "amazon.pl",
}

COUNTRY_TO_LANGUAGE: Dict[str, str] = {
    "us": "en_US",
    "uk": "en_GB",
    "de": "de_DE",
    "fr": "fr_FR",
    "it": "it_IT",
    "es": "es_ES",
    "ca": "en_CA",
    "au": "en_AU",
    "jp": "ja_JP",
    "in": "en_IN",
    "br": "pt_BR",
    "mx": "es_MX",
    "nl": "nl_NL",
    "sg": "en_SG",
    "se": "sv_SE",
    "pl": "pl_PL",
}

DEPARTMENT_TO_INDEX: Dict[str, str] = {
    "electronics": "electronics",
    "computers": "computers",
    "fashion": "fashion",
    "home": "garden",
    "books": "stripbooks",
    "sports": "sporting",
    "toys": "toys-and-games",
    "beauty": "beauty",
    "grocery": "grocery",
    "automotive": "automotive",
    "health": "hpc",
    "music": "popular",
    "movies": "movies-tv",
    "tools": "tools",
    "office": "office-products",
    "pet_supplies": "pet-supplies",
    "video_games": "videogames",
    "baby": "baby-products",
}

SORT_TO_SERPAPI: Dict[str, str] = {
    "relevance": "relevanceblender",
    "price_asc": "price-asc-rank",
    "price_desc": "price-desc-rank",
    "review_rank": "review-rank",
    "newest": "date-desc-rank",
    "best_sellers": "exact-aware-popularity-rank",
}


@dataclass
class AmazonProduct:
    """Normalized Amazon product result for shopping embed rendering."""

    title: str
    purchase_url: Optional[str]
    image_url: Optional[str]
    price: Optional[str]
    price_amount: Optional[float]
    old_price: Optional[str]
    old_price_amount: Optional[float]
    currency_symbol: Optional[str]
    asin: Optional[str]
    rating: Optional[float]
    reviews: Optional[int]
    prime: Optional[bool]
    delivery: List[str]
    bought_last_month: Optional[str]
    sponsored: Optional[bool]
    total_result_count: int

    def to_result_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["type"] = "product"
        # Keep compatibility with existing shopping fullscreen sale logic.
        data["price_eur"] = data["price"]
        return data


def _detect_currency_symbol(price_text: Optional[str], domain: str) -> str:
    if not price_text:
        if domain == "amazon.co.uk":
            return "£"
        if domain in {"amazon.de", "amazon.fr", "amazon.it", "amazon.es", "amazon.nl"}:
            return "€"
        if domain == "amazon.co.jp":
            return "¥"
        if domain == "amazon.in":
            return "₹"
        if domain in {"amazon.com", "amazon.ca", "amazon.com.au", "amazon.sg"}:
            return "$"
        return "$"

    if "€" in price_text:
        return "€"
    if "$" in price_text:
        return "$"
    if "£" in price_text:
        return "£"
    if "¥" in price_text:
        return "¥"
    if "₹" in price_text:
        return "₹"
    return "$"


def infer_country_from_locale(locale_hint: Optional[str]) -> str:
    """
    Infer Amazon country from a locale/language hint.

    Expected examples: "de", "de-DE", "en_US", "fr".
    Falls back to DEFAULT_COUNTRY.
    """
    if not locale_hint:
        return DEFAULT_COUNTRY

    normalized = locale_hint.replace("-", "_").lower().strip()
    if not normalized:
        return DEFAULT_COUNTRY

    parts = normalized.split("_")
    language = parts[0]
    region = parts[1] if len(parts) > 1 else ""

    if region in COUNTRY_TO_DOMAIN:
        return region

    language_default_country = {
        "de": "de",
        "fr": "fr",
        "it": "it",
        "es": "es",
        "ja": "jp",
        "pt": "br",
        "nl": "nl",
        "sv": "se",
        "pl": "pl",
        "hi": "in",
        "tr": "us",
        "ar": "us",
        "zh": "us",
        "en": "us",
    }

    return language_default_country.get(language, DEFAULT_COUNTRY)


def normalize_country(country: Optional[str], locale_hint: Optional[str]) -> str:
    if country and country.strip().lower() in COUNTRY_TO_DOMAIN:
        return country.strip().lower()
    return infer_country_from_locale(locale_hint)


async def search_products(
    query: str,
    *,
    max_results: int = 10,
    sort: str = DEFAULT_SORT,
    country: Optional[str] = None,
    department: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    locale_hint: Optional[str] = None,
    secrets_manager: Optional["SecretsManager"] = None,
) -> tuple[List[AmazonProduct], Dict[str, Any]]:
    """Search Amazon products via SerpAPI and return normalized product results."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("Search query must not be empty.")

    max_results = max(1, min(MAX_RESULTS_LIMIT, int(max_results)))

    sort_value = sort.strip().lower() if sort else DEFAULT_SORT
    serp_sort = SORT_TO_SERPAPI.get(sort_value)
    if not serp_sort:
        raise ValueError(
            "Invalid sort '%s'. Choose from: %s"
            % (sort, list(SORT_TO_SERPAPI.keys()))
        )

    country_code = normalize_country(country, locale_hint)
    amazon_domain = COUNTRY_TO_DOMAIN[country_code]
    language = COUNTRY_TO_LANGUAGE.get(country_code, DEFAULT_LANGUAGE)

    department_value = department.strip().lower() if department else ""
    department_index = None
    if department_value:
        department_index = DEPARTMENT_TO_INDEX.get(department_value)
        if not department_index:
            raise ValueError(
                "Invalid department '%s'. Choose from: %s"
                % (department, list(DEPARTMENT_TO_INDEX.keys()))
            )

    api_key = await get_serpapi_key_async(secrets_manager)
    if not api_key:
        raise ValueError("SerpAPI key not available")

    params: Dict[str, Any] = {
        "engine": "amazon",
        "api_key": api_key,
        "k": cleaned_query,
        "amazon_domain": amazon_domain,
        "language": language,
        "s": serp_sort,
        "page": 1,
    }
    if department_index:
        params["i"] = department_index

    logger.info(
        "Amazon search: query=%r max_results=%d country=%s domain=%s department=%s sort=%s",
        cleaned_query,
        max_results,
        country_code,
        amazon_domain,
        department_value or "none",
        sort_value,
    )

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.get(SERPAPI_BASE, params=params)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error(
            "Amazon SerpAPI request failed query=%r country=%s: %s",
            cleaned_query,
            country_code,
            exc,
            exc_info=True,
        )
        raise

    data = response.json()
    if data.get("error"):
        raise ValueError(f"SerpAPI amazon error: {data.get('error')}")

    search_info = data.get("search_information", {})
    total_result_count = int(search_info.get("total_results") or 0)
    raw_results = data.get("organic_results", [])

    products: List[AmazonProduct] = []
    for raw in raw_results:
        extracted_price = raw.get("extracted_price")
        if min_price is not None and extracted_price is not None and float(extracted_price) < float(min_price):
            continue
        if max_price is not None and extracted_price is not None and float(extracted_price) > float(max_price):
            continue

        price_text = raw.get("price")
        old_price_text = raw.get("old_price")
        currency_symbol = _detect_currency_symbol(price_text, amazon_domain)

        products.append(
            AmazonProduct(
                title=raw.get("title") or "Untitled product",
                purchase_url=raw.get("link_clean") or raw.get("link"),
                image_url=raw.get("thumbnail"),
                price=price_text,
                price_amount=float(extracted_price) if extracted_price is not None else None,
                old_price=old_price_text,
                old_price_amount=(
                    float(raw.get("extracted_old_price"))
                    if raw.get("extracted_old_price") is not None
                    else None
                ),
                currency_symbol=currency_symbol,
                asin=raw.get("asin"),
                rating=float(raw.get("rating")) if raw.get("rating") is not None else None,
                reviews=int(raw.get("reviews")) if raw.get("reviews") is not None else None,
                prime=bool(raw.get("prime")) if raw.get("prime") is not None else None,
                delivery=raw.get("delivery") if isinstance(raw.get("delivery"), list) else [],
                bought_last_month=raw.get("bought_last_month"),
                sponsored=bool(raw.get("sponsored")) if raw.get("sponsored") is not None else None,
                total_result_count=total_result_count,
            )
        )

        if len(products) >= max_results:
            break

    pagination = {
        "page": int(search_info.get("page") or 1),
        "totalPages": 1,
        "totalResultCount": total_result_count,
        "country": country_code,
        "amazon_domain": amazon_domain,
    }
    return products, pagination
