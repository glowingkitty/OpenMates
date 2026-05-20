"""
Stoffe.de product search provider for the shopping app.

Uses the public plentymarkets/Ceres storefront JSON endpoints that power
Stoffe.de search and product pages. This provider needs no cookies, API key,
or proxy and normalizes fabric/sewing product data into the shopping embed
product shape used by shopping.search_products.

Architecture: provider-only HTTP layer for shopping.search_products.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://www.stoffe.de/rest/io/item/search"
PRODUCT_PAGE_BASE = "https://www.stoffe.de"

MAX_RESULTS_LIMIT = 20

SORT_OPTIONS: dict[str, str] = {
    "relevance": "item.score",
    "price_asc": "sorting.price.avg_asc",
    "price_desc": "sorting.price.avg_desc",
    "new": "variation.id_desc",
    "name_asc": "texts.name1_asc",
    "name_desc": "texts.name1_desc",
}

DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Referer": "https://www.stoffe.de/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class StoffeProduct:
    """Normalized Stoffe.de product result for shopping embed rendering."""

    product_id: str
    variation_id: Optional[str]
    title: str
    brand: Optional[str]
    price: Optional[str]
    price_amount: Optional[float]
    base_price: Optional[str]
    currency: Optional[str]
    unit: Optional[str]
    stock: Optional[float]
    availability: Optional[str]
    is_salable: bool
    purchase_url: str
    image_url: Optional[str]
    category_path: Optional[str]
    category_ids: list[str]
    attributes: dict[str, Any]
    color_child_item_ids: list[str]
    search_rank: int = 0

    def to_result_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = "product"
        data["price_eur"] = data["price"]
        return data


def _flatten_variation_properties(raw: dict[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for group in raw.get("variationProperties") or []:
        properties = group.get("properties")
        if isinstance(properties, list):
            for prop in properties:
                name = (prop.get("names") or {}).get("name")
                value = (prop.get("values") or {}).get("value")
                if name and value not in (None, ""):
                    attributes[name] = value
            continue

        prop = group.get("property")
        if isinstance(prop, dict):
            name = (prop.get("names") or {}).get("name")
            value = (group.get("values") or {}).get("value")
            if name and value not in (None, ""):
                attributes[name] = value
    return attributes


def _parse_color_child_ids(raw: dict[str, Any], attributes: dict[str, Any]) -> list[str]:
    candidates: list[Any] = [
        (raw.get("item") or {}).get("free1"),
        attributes.get("Farbartikel IDs der Child"),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if isinstance(candidate, list):
            return _valid_item_ids(str(item_id) for item_id in candidate)
        if isinstance(candidate, str):
            value = candidate.strip()
            if not value:
                continue
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return _valid_item_ids(str(item_id) for item_id in parsed)
            except json.JSONDecodeError:
                pass
            return _valid_item_ids(re.findall(r"\d+", value))

    return []


def _valid_item_ids(values: Any) -> list[str]:
    return [value for value in values if re.fullmatch(r"\d{8}", value.strip())]


def _first_property_value(attributes: dict[str, Any], key: str) -> Optional[str]:
    value = attributes.get(key)
    return str(value).strip() if value not in (None, "") else None


def _build_purchase_url(
    item_id: str,
    raw: dict[str, Any],
    attributes: dict[str, Any],
) -> str:
    slug = _first_property_value(attributes, "URL") or (raw.get("texts") or {}).get(
        "urlPath"
    )
    if not slug:
        slug = _slugify((raw.get("texts") or {}).get("name1") or item_id)
    return f"{PRODUCT_PAGE_BASE}/{str(slug).strip('/')}/a-{item_id}/"


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_product(raw: dict[str, Any], rank: int) -> StoffeProduct:
    item = raw.get("item") or {}
    variation = raw.get("variation") or {}
    texts = raw.get("texts") or {}
    prices = (raw.get("prices") or {}).get("default") or {}
    price = prices.get("price") or {}
    unit = raw.get("unit") or {}
    filter_data = raw.get("filter") or {}
    stock = raw.get("stock") or {}
    images = (raw.get("images") or {}).get("all") or []
    manufacturer = item.get("manufacturer") or {}

    item_id = str(item.get("id") or texts.get("itemId") or "")
    attributes = _flatten_variation_properties(raw)
    title = (
        _first_property_value(attributes, "Name 1")
        or texts.get("name1")
        or "Untitled product"
    )

    category_ids = [
        str(category_id)
        for category_id in (raw.get("ids") or {})
        .get("categories", {})
        .get("branches", [])
    ]
    if not category_ids:
        category_ids = [
            str(category.get("id"))
            for category in raw.get("defaultCategories") or []
            if category.get("id") is not None
        ]

    image_url = (
        images[0].get("urlPreview")
        if images and isinstance(images[0], dict)
        else None
    )
    availability = ((variation.get("availability") or {}).get("names") or {}).get("name")

    return StoffeProduct(
        product_id=item_id,
        variation_id=str(variation.get("id")) if variation.get("id") is not None else None,
        title=title,
        brand=(
            manufacturer.get("externalName")
            or manufacturer.get("nameExternal")
            or manufacturer.get("name")
        ),
        price=price.get("formatted"),
        price_amount=_parse_float(price.get("value")),
        base_price=prices.get("basePrice") or None,
        currency=prices.get("currency"),
        unit=(
            (unit.get("names") or {}).get("name")
            if isinstance(unit.get("names"), dict)
            else None
        ),
        stock=_parse_float(stock.get("net")),
        availability=availability,
        is_salable=bool(filter_data.get("isSalable")),
        purchase_url=_build_purchase_url(item_id, raw, attributes),
        image_url=image_url,
        category_path=None,
        category_ids=category_ids,
        attributes=attributes,
        color_child_item_ids=_parse_color_child_ids(raw, attributes),
        search_rank=rank,
    )


def _slugify(title: str) -> str:
    value = title.lower()
    for umlaut, replacement in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        value = value.replace(umlaut, replacement)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


async def search_products(
    query: str,
    *,
    max_results: int = 10,
    sort: str = "relevance",
) -> tuple[list[StoffeProduct], dict[str, Any]]:
    """Search Stoffe.de products through the public plentymarkets storefront API."""

    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("Search query must not be empty.")

    max_results = max(1, min(MAX_RESULTS_LIMIT, int(max_results)))
    sort_value = sort.strip().lower() if sort else "relevance"
    sort_param = SORT_OPTIONS.get(sort_value)
    if not sort_param:
        raise ValueError(f"Invalid sort '{sort}'. Choose from: {list(SORT_OPTIONS)}")

    params = {
        "query": cleaned_query,
        "items": max_results,
        "page": 1,
        "sorting": sort_param,
    }

    logger.info(
        "Stoffe.de search: query=%r max_results=%d sort=%s",
        cleaned_query,
        max_results,
        sort_value,
    )

    try:
        async with create_http_client(
            "stoffe",
            follow_redirects=True,
            timeout=20.0,
        ) as client:
            response = await client.get(SEARCH_API_URL, headers=DEFAULT_HEADERS, params=params)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error(
            "Stoffe.de request failed query=%r: %s",
            cleaned_query,
            exc,
            exc_info=True,
        )
        raise

    try:
        data = response.json()
    except Exception as exc:
        raise ValueError(f"Non-JSON response from Stoffe.de API: {exc}") from exc

    item_list = (data.get("data") or {}).get("itemList") or {}
    raw_documents = item_list.get("documents") or []
    total = int(item_list.get("total") or 0)

    products = [
        _parse_product(document.get("data") or {}, rank)
        for rank, document in enumerate(raw_documents[:max_results], start=1)
    ]

    pagination = {
        "page": 1,
        "totalPages": max(1, (total + max_results - 1) // max_results) if total else 1,
        "totalResultCount": total,
    }

    logger.info("Stoffe.de: %d results returned (%d total)", len(products), total)
    return products, pagination
