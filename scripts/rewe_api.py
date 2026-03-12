"""
REWE Online Shop — Reverse-Engineered API Client
=================================================
Searches products on shop.rewe.de using the internal REST API discovered by
analysing network traffic from the REWE web app.

Discovered endpoints (reverse-engineered)
------------------------------------------
  Search API  : GET https://shop.rewe.de/api/products
                  → 301 redirects to https://www.rewe.de/shop/api/products
                  → Returns HAL+JSON with _embedded.products list
                  → Query params: search, serviceTypes, sorting,
                                  objectsPerPage, page, marketCode

  Pricing     : Pricing is market-specific and requires an active session
                with a selected delivery location (Cloudflare-protected).
                Without a session, price is "Preis abhängig vom Standort".
                With --market-code the API returns market-scoped product lists
                (availability / assortment may differ).

  Product URL : https://shop.rewe.de/p/{slug}/{productId}
                  slug is embedded in _links.detail.href

Response structure (new HAL format)
-------------------------------------
  {
    "type": "SEARCH_RESULT",
    "pagination": { "page": 1, "totalPages": ..., "totalResultCount": ... },
    "_embedded": {
      "products": [
        {
          "id": "677067",
          "productName": "Weihenstephan H-Milch 3,5% 1l",
          "brand": { "name": "Weihenstephan" },
          "media": { "images": [{ "_links": { "self": { "href": "..." } } }] },
          "_embedded": {
            "articles": [],              ← non-empty only with auth session
            "categories": [ ... ],
            "categoryPath": "Käse, Eier & Molkerei/Milch/H-Milch/"
          },
          "_links": {
            "detail": { "href": "/p/weihenstephan-h-milch-3-5-1l/677067" }
          },
          "attributes": {}
        }
      ]
    }
  }

Usage (CLI)
-----------
  python3 rewe_api.py "milch" --limit 5
  python3 rewe_api.py "bio joghurt" --limit 10 --format json
  python3 rewe_api.py "brot" --sort price_asc
  python3 rewe_api.py "käse" --market-code 5841901
  python3 rewe_api.py "apfel" --limit 20 --out results.json
  python3 rewe_api.py "wasser" --service-type CLICK_AND_COLLECT --page 2
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rewe_api")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Primary search endpoint (redirects to www.rewe.de/shop/api/products)
SEARCH_API_URL = "https://shop.rewe.de/api/products"

# Product page base (for building purchase URLs)
PRODUCT_PAGE_BASE = "https://shop.rewe.de"

# Sorting options (API parameter → human label)
SORT_OPTIONS: dict[str, str] = {
    "relevance": "RELEVANCE_DESC",
    "price_asc": "PRICE_ASC",
    "price_desc": "PRICE_DESC",
    "new": "NEW_DESC",
}

# Valid service types
SERVICE_TYPES = {"DELIVERY", "CLICK_AND_COLLECT"}

# Default request headers — mimic a real browser to avoid 403s
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://shop.rewe.de/",
}

# Polite delay between requests (seconds)
REQUEST_DELAY = 0.4

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ProductAttributes:
    """Dietary and product type flags returned by the REWE API."""

    is_organic: bool = False
    is_vegan: bool = False
    is_vegetarian: bool = False
    is_dairy_free: bool = False
    is_gluten_free: bool = False
    is_new: bool = False
    is_regional: bool = False
    is_lowest_price: bool = False
    is_bulky_good: bool = False


@dataclass
class REWEProduct:
    """
    A single REWE product with all available metadata.

    Pricing note
    ------------
    REWE prices are market-specific (differ by delivery location) and are only
    served to authenticated sessions with a selected market. Without a session
    the price field is None. Pass --market-code to scope results to a specific
    market (affects assortment/availability but does not unlock prices).
    """

    # Core identity
    product_id: str
    title: str

    # URLs
    purchase_url: str               # Full URL to product page on shop.rewe.de
    image_url: Optional[str]        # Product image (PNG, hosted on img.rewe-static.de)

    # Classification
    brand: Optional[str]
    category_path: Optional[str]    # e.g. "Käse, Eier & Molkerei/Milch/H-Milch/"
    category_ids: list[str]

    # Attributes / dietary flags
    attributes: ProductAttributes

    # Limits & fulfilment
    order_limit: Optional[int]      # Max units per order (from articles when available)
    free_shipping: bool = False

    # Search metadata
    search_rank: int = 0            # 1-indexed position in search results

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)

    def summary_line(self) -> str:
        """One-line summary for terminal output."""
        brand_part = f" ({self.brand})" if self.brand else ""
        cat_part = f" [{self.category_path.rstrip('/')}]" if self.category_path else ""
        return f"#{self.search_rank:>3}  {self.title}{brand_part}{cat_part}"

    def detail_block(self) -> str:
        """Multi-line detail block for terminal output."""
        lines = [
            f"{'─'*60}",
            f"#{self.search_rank}  {self.title}",
        ]
        if self.brand:
            lines.append(f"     Brand    : {self.brand}")
        lines.append("     Price    : n/a (market-specific — see URL)")
        if self.category_path:
            lines.append(f"     Category : {self.category_path.rstrip('/')}")
        lines.append(f"     URL      : {self.purchase_url}")
        if self.image_url:
            lines.append(f"     Image    : {self.image_url}")
        # Dietary flags
        flags = [
            label
            for label, val in [
                ("Organic", self.attributes.is_organic),
                ("Vegan", self.attributes.is_vegan),
                ("Vegetarian", self.attributes.is_vegetarian),
                ("Dairy-free", self.attributes.is_dairy_free),
                ("Gluten-free", self.attributes.is_gluten_free),
                ("New", self.attributes.is_new),
                ("Regional", self.attributes.is_regional),
                ("Lowest price", self.attributes.is_lowest_price),
            ]
            if val
        ]
        if flags:
            lines.append(f"     Tags     : {', '.join(flags)}")
        if self.order_limit:
            lines.append(f"     Max qty  : {self.order_limit}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------


class REWESession:
    """
    Manages an HTTP session for REWE API calls.

    Persists cookies and headers across requests. Visiting the homepage first
    obtains Cloudflare cookies that improve reliability on subsequent calls.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request: float = 0.0
        self._warmed_up = False

    def _rate_limit(self) -> None:
        """Sleep if needed to respect the per-request delay."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request = time.monotonic()

    def warmup(self) -> None:
        """
        Visit the REWE shop homepage to acquire Cloudflare session cookies.

        The search API works without this, but a warmed-up session reduces
        the chance of transient 403s on subsequent requests.
        """
        if self._warmed_up:
            return
        try:
            self._rate_limit()
            self.session.get(
                "https://shop.rewe.de/",
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
                timeout=12,
                allow_redirects=True,
            )
            logger.debug("Session warmed up (homepage visited)")
        except requests.RequestException as e:
            logger.debug("Warmup request failed (non-fatal): %s", e)
        finally:
            self._warmed_up = True

    def get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET with error logging."""
        self._rate_limit()
        logger.debug("GET %s", url)
        response = self.session.get(url, timeout=15, **kwargs)
        response.raise_for_status()
        return response


# ---------------------------------------------------------------------------
# Product parsing
# ---------------------------------------------------------------------------


def _parse_attributes(raw: dict) -> ProductAttributes:
    """Parse the attributes dict from the API response."""
    # New API returns an empty {} for attributes; old mobile API has keys.
    return ProductAttributes(
        is_organic=raw.get("isOrganic") or raw.get("bio", False),
        is_vegan=raw.get("isVegan", False),
        is_vegetarian=raw.get("isVegetarian", False),
        is_dairy_free=raw.get("isDairyFree", False),
        is_gluten_free=raw.get("isGlutenFree", False),
        is_new=raw.get("isNew", False),
        is_regional=raw.get("isRegional", False),
        is_lowest_price=raw.get("isLowestPrice", False),
        is_bulky_good=raw.get("isBulkyGood", False),
    )


def _parse_product(raw: dict, rank: int) -> REWEProduct:
    """
    Parse a product dict from the REWE search API into a REWEProduct.

    Handles both the new HAL format (_embedded, _links) and the legacy mobile
    format (productId, imageURL, categories at top level).

    Args:
        raw:  Raw product dict from API response.
        rank: 1-indexed position in search results.
    """
    # --- Identity ---
    # New format uses "id", legacy uses "productId"
    product_id = raw.get("id") or raw.get("productId", "")
    title = raw.get("productName") or raw.get("title", "Unknown")

    # --- Purchase URL ---
    # New format: _links.detail.href = "/p/weihenstephan-h-milch-3-5-1l/677067"
    detail_href = raw.get("_links", {}).get("detail", {}).get("href", "")
    if detail_href:
        purchase_url = f"{PRODUCT_PAGE_BASE}{detail_href}"
    else:
        # Fallback: build URL from product ID (slug derived from title)
        slug = _slugify(title)
        purchase_url = f"{PRODUCT_PAGE_BASE}/p/{slug}/{product_id}"

    # --- Image ---
    image_url: Optional[str] = None
    media = raw.get("media", {})
    if media:
        images = media.get("images", [])
        if images:
            image_url = images[0].get("_links", {}).get("self", {}).get("href")
    if not image_url:
        # Legacy format has imageURL directly
        image_url = raw.get("imageURL")

    # --- Brand ---
    brand_obj = raw.get("brand")
    brand: Optional[str] = None
    if isinstance(brand_obj, dict):
        brand = brand_obj.get("name")
    elif isinstance(brand_obj, str):
        brand = brand_obj

    # --- Categories ---
    embedded = raw.get("_embedded", {})
    category_path: Optional[str] = embedded.get("categoryPath")

    raw_cats = embedded.get("categories", raw.get("categories", []))
    category_ids: list[str] = []
    for cat in raw_cats:
        if isinstance(cat, dict):
            category_ids.append(str(cat.get("id", "")))
        else:
            category_ids.append(str(cat))

    # --- Attributes ---
    attributes = _parse_attributes(raw.get("attributes", {}))

    # --- Order limit (comes from articles when session is active) ---
    articles = embedded.get("articles", [])
    order_limit: Optional[int] = raw.get("orderLimit")
    if articles:
        order_limit = articles[0].get("orderLimit", order_limit)

    return REWEProduct(
        product_id=product_id,
        title=title,
        purchase_url=purchase_url,
        image_url=image_url,
        brand=brand,
        category_path=category_path,
        category_ids=category_ids,
        attributes=attributes,
        order_limit=order_limit,
        free_shipping=raw.get("freeShipping", False),
        search_rank=rank,
    )


def _slugify(title: str) -> str:
    """
    Convert a product title to a URL slug (best-effort approximation of REWE's format).

    REWE slugs are lowercase kebab-case with Umlauts expanded. The canonical
    slug is always in _links.detail.href when available — use that instead.

    Example: "Weihenstephan H-Milch 3,5% 1l" → "weihenstephan-h-milch-3-5-1l"
    """
    s = title.lower()
    for umlaut, replacement in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        s = s.replace(umlaut, replacement)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search(
    query: str,
    *,
    limit: int = 10,
    page: int = 1,
    sort: str = "relevance",
    service_type: str = "DELIVERY",
    market_code: Optional[str] = None,
    session: Optional[REWESession] = None,
) -> tuple[list[REWEProduct], dict[str, Any]]:
    """
    Search for products on the REWE online shop.

    Calls the internal REWE product search API (the same one the REWE mobile
    app and SPA use) and returns structured product objects.

    Args:
        query:        Search term in German or English, e.g. "milch", "bio joghurt".
        limit:        Max products to return per call (1–100, default 10).
        page:         Page number for pagination, 1-indexed (default 1).
        sort:         Sort order: "relevance" | "price_asc" | "price_desc" | "new".
        service_type: "DELIVERY" (default) or "CLICK_AND_COLLECT".
        market_code:  Optional REWE market ID (e.g. "5841901" for Berlin Mitte).
                      Scopes assortment to that market. Known codes:
                        5841901 — Berlin Mitte
                        5340503 — München Maxvorstadt
                      Find yours by selecting a location on shop.rewe.de and
                      inspecting the marketCode query param in network requests.
        session:      Optional pre-created REWESession (created internally if None).

    Returns:
        Tuple of (products, pagination_info):
          products        — list of REWEProduct
          pagination_info — dict with keys: page, totalPages, totalResultCount

    Raises:
        ValueError:              On invalid parameters.
        requests.HTTPError:      On 4xx/5xx API responses.
        requests.RequestException: On network failures.
    """
    # Validate
    query = query.strip()
    if not query:
        raise ValueError("Search query must not be empty.")
    limit = max(1, min(100, limit))
    page = max(1, page)
    sort_param = SORT_OPTIONS.get(sort)
    if not sort_param:
        raise ValueError(f"Invalid sort '{sort}'. Choose from: {list(SORT_OPTIONS)}")
    service_type = service_type.upper()
    if service_type not in SERVICE_TYPES:
        raise ValueError(f"Invalid service_type '{service_type}'. Choose from: {list(SERVICE_TYPES)}")

    if session is None:
        session = REWESession()

    # Build query parameters
    params: dict[str, Any] = {
        "search": query,
        "serviceTypes": service_type,
        "sorting": sort_param,
        "objectsPerPage": limit,
        "page": page,
    }
    if market_code:
        params["marketCode"] = market_code

    logger.info(
        "Searching REWE: query=%r limit=%d page=%d sort=%s%s",
        query, limit, page, sort,
        f" market={market_code}" if market_code else "",
    )

    response = session.get(SEARCH_API_URL, params=params)

    # Parse response
    # The API redirects to www.rewe.de/shop/api/products which returns HAL+JSON:
    # { "_embedded": { "products": [...] }, "pagination": { ... }, ... }
    try:
        data = response.json()
    except Exception as e:
        raise ValueError(f"Non-JSON response from REWE API: {e}") from e

    # Extract products — handle both HAL format and legacy mobile format
    raw_products: list[dict] = (
        data.get("_embedded", {}).get("products")        # new HAL format
        or data.get("products")                          # legacy mobile format
        or []
    )

    # Pagination info
    pag = data.get("pagination", {})
    pagination = {
        "page":             pag.get("page", pag.get("currentPage", page)),
        "totalPages":       pag.get("totalPages", pag.get("pageCount", 1)),
        "totalResultCount": pag.get("totalResultCount", pag.get("objectCount", 0)),
    }

    logger.info(
        "  → %d results on this page (%d total across %d pages)",
        len(raw_products),
        pagination["totalResultCount"],
        pagination["totalPages"],
    )

    # Convert raw dicts to REWEProduct objects
    offset = (page - 1) * limit
    products = [_parse_product(raw, offset + i + 1) for i, raw in enumerate(raw_products)]

    return products, pagination


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def format_text(products: list[REWEProduct], query: str, pagination: dict) -> str:
    """Format products as a human-readable terminal output."""
    lines = [
        f"\nREWE Search: \"{query}\"",
        f"Showing {len(products)} of {pagination['totalResultCount']} results "
        f"(page {pagination['page']}/{pagination['totalPages']})",
        "",
    ]
    for p in products:
        lines.append(p.detail_block())
    lines.append(f"{'─'*60}")
    lines.append(
        "Note: Prices are market-specific. Visit the URL to see the price for your area."
    )
    return "\n".join(lines)


def format_json(products: list[REWEProduct], query: str, pagination: dict) -> str:
    """Format products as a JSON string."""
    return json.dumps(
        {
            "query": query,
            "pagination": pagination,
            "products": [p.to_dict() for p in products],
        },
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rewe_api.py",
        description="Search the REWE online shop from the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 rewe_api.py "milch"
  python3 rewe_api.py "bio joghurt" --limit 10
  python3 rewe_api.py "brot" --sort price_asc --format json
  python3 rewe_api.py "käse" --market-code 5841901
  python3 rewe_api.py "apfel" --limit 20 --out results.json
  python3 rewe_api.py "wasser" --page 2 --service-type CLICK_AND_COLLECT
        """,
    )
    parser.add_argument("query", help='Search term, e.g. "milch" or "bio joghurt"')
    parser.add_argument(
        "--limit", "-l", type=int, default=10, metavar="N",
        help="Max products to return (1–100, default: 10)",
    )
    parser.add_argument(
        "--page", "-p", type=int, default=1, metavar="N",
        help="Results page number (default: 1)",
    )
    parser.add_argument(
        "--sort", "-s", choices=list(SORT_OPTIONS), default="relevance",
        help="Sort order (default: relevance)",
    )
    parser.add_argument(
        "--service-type", choices=list(SERVICE_TYPES), default="DELIVERY",
        dest="service_type",
        help="Service type (default: DELIVERY)",
    )
    parser.add_argument(
        "--market-code", "-m", default=None, dest="market_code",
        metavar="CODE",
        help="REWE market ID to scope assortment (e.g. 5841901 for Berlin Mitte)",
    )
    parser.add_argument(
        "--format", "-f", choices=["text", "json"], default="text",
        dest="output_format",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--out", "-o", default=None, metavar="FILE",
        help="Save output to a file instead of (or in addition to) stdout",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose debug logging",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    session = REWESession()
    session.warmup()

    try:
        products, pagination = search(
            query=args.query,
            limit=args.limit,
            page=args.page,
            sort=args.sort,
            service_type=args.service_type,
            market_code=args.market_code,
            session=session,
        )
    except ValueError as e:
        logger.error("Bad argument: %s", e)
        return 1
    except requests.HTTPError as e:
        logger.error("HTTP error from REWE API: %s", e)
        return 2
    except requests.RequestException as e:
        logger.error("Network error: %s", e)
        return 2

    if not products:
        print(f'No products found for "{args.query}".')
        return 0

    # Format output
    if args.output_format == "json":
        output = format_json(products, args.query, pagination)
    else:
        output = format_text(products, args.query, pagination)

    # Print to stdout
    print(output)

    # Optionally save to file
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(output)
                fh.write("\n")
            logger.info("Results saved to %s", args.out)
        except OSError as e:
            logger.error("Could not write to %s: %s", args.out, e)
            return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
