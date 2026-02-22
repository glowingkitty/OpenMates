"""
REWE Online Shop Provider
=========================
Authenticates and executes product searches against the internal REWE REST API
(shop.rewe.de/api/products → redirects to www.rewe.de/shop/api/products).

Architecture
------------
REWE uses Cloudflare protection. The key cookies (cf_clearance, __cf_bm, mtc,
rstp, lantern) are IP-bound: a cookie harvested on one IP is only valid when
requests come from the same IP.

Therefore:
  1.  A Playwright browser session visits shop.rewe.de, selects a delivery
      location (PLZ), and harvests cookies.  This is done externally once per
      day (or whenever the cookie pool expires) and stored in Vault at:
        kv/data/providers/rewe
      Format:
        {
          "cookie_pool": [
            {
              "cookies": "cf_clearance=...; __cf_bm=...; ...",
              "proxy": "http://user:pass@proxy-host:port",
              "user_agent": "Mozilla/5.0 ...",
              "harvested_at": "2026-02-22T10:00:00Z"
            },
            ...  (up to 5 entries)
          ]
        }

  2.  The provider picks the freshest cookie entry from the pool and routes
      every API request through the matching residential proxy IP.

  3.  We rotate through pool entries on failure so the skill stays available
      even if one entry expires mid-session.

Cookie pool refresh
-------------------
Cookies expire in ~24 h.  Refresh is triggered externally by a cron job or
Playwright script.  This provider is read-only with respect to Vault; it does
not refresh the pool itself.

See: docs/architecture/shopping-cookie-pool.md (TODO: write this doc)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# REWE search endpoint (redirects to www.rewe.de/shop/api/products)
SEARCH_API_URL = "https://shop.rewe.de/api/products"

# Product page base for building purchase URLs
PRODUCT_PAGE_BASE = "https://shop.rewe.de"

# Vault secret path for REWE cookie pool
VAULT_SECRET_PATH = "kv/data/providers/rewe"

# Sorting options: public name → API parameter
SORT_OPTIONS: dict[str, str] = {
    "relevance": "RELEVANCE_DESC",
    "price_asc": "PRICE_ASC",
    "price_desc": "PRICE_DESC",
    "new": "NEW_DESC",
}

# Default request headers — mimic a real browser
DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://shop.rewe.de/",
}

# Maximum age in seconds before a cookie pool entry is considered stale (24 h)
MAX_COOKIE_AGE_SECONDS = 86_400

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ProductAttributes:
    """Dietary and product-type flags returned by the REWE API."""

    is_organic: bool = False
    is_vegan: bool = False
    is_vegetarian: bool = False
    is_dairy_free: bool = False
    is_gluten_free: bool = False
    is_new: bool = False
    is_regional: bool = False
    is_lowest_price: bool = False


@dataclass
class REWEProduct:
    """
    A single REWE product with pricing and metadata.

    Pricing fields (price_cents, was_price_cents, grammage) are populated
    only when requests are made with an authenticated session (cookie pool).
    Without authentication the REWE API returns an empty articles list and
    price is None.
    """

    # Core identity
    product_id: str
    title: str
    brand: Optional[str]

    # Pricing (market-specific, requires auth session)
    price_cents: Optional[int]          # Current retail price in euro-cents
    was_price_cents: Optional[int]      # Regular price (if product is on sale)
    grammage: Optional[str]             # e.g. "500g (1 kg = 2,78 €)"
    deposit_cents: Optional[int]        # Pfand deposit in euro-cents

    # URLs
    purchase_url: str                   # https://shop.rewe.de/p/{slug}/{id}
    image_url: Optional[str]

    # Classification
    category_path: Optional[str]        # e.g. "Käse, Eier & Molkerei/Milch/"
    category_ids: list[str]

    # Dietary flags
    attributes: ProductAttributes

    # Limits
    order_limit: Optional[int]

    # Search metadata
    search_rank: int = 0

    def price_eur(self) -> Optional[str]:
        """Return formatted price like '1,39 €' or None if unavailable."""
        if self.price_cents is None:
            return None
        return f"{self.price_cents / 100:.2f} €".replace(".", ",")

    def to_result_dict(self) -> dict[str, Any]:
        """
        Return a JSON-serialisable dict suitable for the skill response.

        Field names match what the frontend ShoppingSearchEmbedPreview expects.
        """
        d = asdict(self)
        # Add human-readable price
        d["price_eur"] = self.price_eur()
        d["type"] = "product"
        return d


# ---------------------------------------------------------------------------
# Cookie pool helper
# ---------------------------------------------------------------------------


def _pick_freshest_cookie_entry(pool: list[dict]) -> Optional[dict]:
    """
    Pick the freshest (most recently harvested) non-stale cookie entry.

    Args:
        pool: List of cookie pool dicts from Vault.

    Returns:
        The freshest entry, or None if all entries are stale/missing.
    """
    if not pool:
        return None

    valid: list[dict] = []
    now = time.time()

    for entry in pool:
        harvested_at_str = entry.get("harvested_at", "")
        if harvested_at_str:
            try:
                import datetime
                harvested_at = datetime.datetime.fromisoformat(
                    harvested_at_str.replace("Z", "+00:00")
                ).timestamp()
                age = now - harvested_at
                if age > MAX_COOKIE_AGE_SECONDS:
                    logger.warning(
                        "REWE cookie entry is %.0f hours old — may be stale",
                        age / 3600,
                    )
                    # Include stale entries as fallback, mark them lower priority
                    valid.append((age, entry))
                    continue
            except ValueError:
                pass
        # Unknown age — include at low priority
        valid.append((float("inf"), entry))

    if not valid:
        return None

    # Sort by age ascending (freshest first)
    valid.sort(key=lambda x: x[0])
    return valid[0][1]


# ---------------------------------------------------------------------------
# Product parsing
# ---------------------------------------------------------------------------


def _parse_attributes(raw: dict) -> ProductAttributes:
    """
    Parse the 'attributes' dict from the REWE API response.

    With an authenticated session the 'tags' field is populated:
      raw = {"tags": {"organic": {"label": "Bio"}, ...}}
    Without a session, raw is typically an empty dict.
    """
    tags = raw.get("tags", {}) if isinstance(raw, dict) else {}
    return ProductAttributes(
        is_organic=bool(tags.get("organic") or raw.get("isOrganic") or raw.get("bio")),
        is_vegan=bool(tags.get("vegan") or raw.get("isVegan")),
        is_vegetarian=bool(tags.get("vegetarian") or raw.get("isVegetarian")),
        is_dairy_free=bool(tags.get("dairyFree") or raw.get("isDairyFree")),
        is_gluten_free=bool(tags.get("glutenFree") or raw.get("isGlutenFree")),
        is_new=bool(tags.get("new") or raw.get("isNew")),
        is_regional=bool(tags.get("regional") or raw.get("isRegional")),
        is_lowest_price=bool(tags.get("lowestPrice") or raw.get("isLowestPrice")),
    )


def _parse_product(raw: dict, rank: int) -> REWEProduct:
    """
    Parse a product dict from the REWE search API into a REWEProduct.

    Handles both authenticated (articles populated, prices available) and
    unauthenticated (articles empty, no prices) responses.
    """
    # Identity
    product_id = raw.get("id") or raw.get("productId", "")
    title = raw.get("productName") or raw.get("title", "Unknown")

    # Purchase URL from HAL links
    detail_href = raw.get("_links", {}).get("detail", {}).get("href", "")
    if detail_href:
        purchase_url = f"{PRODUCT_PAGE_BASE}{detail_href}"
    else:
        slug = _slugify(title)
        purchase_url = f"{PRODUCT_PAGE_BASE}/p/{slug}/{product_id}"

    # Image
    image_url: Optional[str] = None
    media = raw.get("media", {})
    if media:
        images = media.get("images", [])
        if images:
            image_url = images[0].get("_links", {}).get("self", {}).get("href")
    if not image_url:
        image_url = raw.get("imageURL")

    # Brand
    brand_obj = raw.get("brand")
    brand: Optional[str] = None
    if isinstance(brand_obj, dict):
        brand = brand_obj.get("name")
    elif isinstance(brand_obj, str):
        brand = brand_obj

    # Categories
    embedded = raw.get("_embedded", {})
    category_path: Optional[str] = embedded.get("categoryPath")
    raw_cats = embedded.get("categories", raw.get("categories", []))
    category_ids: list[str] = [
        str(c.get("id", "") if isinstance(c, dict) else c) for c in raw_cats
    ]

    # Attributes / dietary flags
    attributes = _parse_attributes(raw.get("attributes", {}))

    # Pricing from articles (requires authenticated session)
    articles = embedded.get("articles", [])
    price_cents: Optional[int] = None
    was_price_cents: Optional[int] = None
    grammage: Optional[str] = None
    deposit_cents: Optional[int] = None
    order_limit: Optional[int] = raw.get("orderLimit")

    if articles:
        first = articles[0]
        listing = first.get("_embedded", {}).get("listing", {})
        pricing = listing.get("pricing", {})

        price_cents = pricing.get("currentRetailPrice")
        was_price_cents = pricing.get("regularRetailPrice")
        grammage = pricing.get("grammage")
        deposit_cents = pricing.get("totalRefund")

        limitations = listing.get("limitations", {})
        order_limit = limitations.get("orderLimit", order_limit)

    return REWEProduct(
        product_id=product_id,
        title=title,
        brand=brand,
        price_cents=price_cents,
        was_price_cents=was_price_cents,
        grammage=grammage,
        deposit_cents=deposit_cents,
        purchase_url=purchase_url,
        image_url=image_url,
        category_path=category_path,
        category_ids=category_ids,
        attributes=attributes,
        order_limit=order_limit,
        search_rank=rank,
    )


def _slugify(title: str) -> str:
    """Convert a product title to a URL slug (best-effort REWE approximation)."""
    s = title.lower()
    for umlaut, rep in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        s = s.replace(umlaut, rep)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------


async def search_products(
    query: str,
    *,
    max_results: int = 10,
    sort: str = "relevance",
    service_type: str = "DELIVERY",
    secrets_manager: Optional["SecretsManager"] = None,
) -> tuple[list[REWEProduct], dict[str, Any]]:
    """
    Search REWE products with authenticated pricing.

    Loads cookie pool from Vault (via secrets_manager), picks the freshest
    entry, and routes the request through the associated residential proxy.

    Args:
        query:          Search term, e.g. "bio joghurt" or "pasta barilla".
        max_results:    Maximum products to return (1–20).
        sort:           Sort order: "relevance" | "price_asc" | "price_desc" | "new".
        service_type:   "DELIVERY" or "CLICK_AND_COLLECT".
        secrets_manager: SecretsManager for loading the cookie pool from Vault.

    Returns:
        Tuple of (products, pagination_info):
          products        — list of REWEProduct (with prices if auth succeeded)
          pagination_info — dict with page, totalPages, totalResultCount

    Raises:
        ValueError:  On invalid parameters.
        httpx.HTTPError: On HTTP errors.
    """
    query = query.strip()
    if not query:
        raise ValueError("Search query must not be empty.")

    max_results = max(1, min(20, max_results))
    sort_param = SORT_OPTIONS.get(sort)
    if not sort_param:
        raise ValueError(f"Invalid sort '{sort}'. Choose from: {list(SORT_OPTIONS)}")

    service_type = service_type.upper()
    if service_type not in ("DELIVERY", "CLICK_AND_COLLECT"):
        raise ValueError(f"Invalid service_type '{service_type}'.")

    # Load cookie pool from Vault
    cookie_entry: Optional[dict] = None
    proxy_url: Optional[str] = None
    user_agent: Optional[str] = None

    if secrets_manager:
        try:
            secret_data = await secrets_manager.get_secret(VAULT_SECRET_PATH)
            pool = secret_data.get("cookie_pool", [])
            cookie_entry = _pick_freshest_cookie_entry(pool)
            if cookie_entry:
                proxy_url = cookie_entry.get("proxy")
                user_agent = cookie_entry.get("user_agent")
                logger.info(
                    "REWE cookie pool: using entry harvested_at=%s",
                    cookie_entry.get("harvested_at", "unknown"),
                )
            else:
                logger.warning(
                    "REWE cookie pool is empty or all entries are stale. "
                    "Proceeding without authentication — prices will be unavailable."
                )
        except Exception as e:
            logger.error("Failed to load REWE cookie pool from Vault: %s", e, exc_info=True)
            # Proceed without cookies — no prices, but basic product data still works
    else:
        logger.warning(
            "No secrets_manager provided to REWE provider. "
            "Prices will be unavailable."
        )

    # Build request headers
    headers = dict(DEFAULT_HEADERS)
    if user_agent:
        headers["User-Agent"] = user_agent
    else:
        headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    if cookie_entry:
        cookie_str = cookie_entry.get("cookies", "")
        if cookie_str:
            headers["Cookie"] = cookie_str

    # Build query parameters
    params: dict[str, Any] = {
        "search": query,
        "serviceTypes": service_type,
        "sorting": sort_param,
        "objectsPerPage": max_results,
        "page": 1,
    }

    logger.info(
        "REWE search: query=%r max_results=%d sort=%s auth=%s proxy=%s",
        query, max_results, sort,
        "yes" if cookie_entry else "no",
        "yes" if proxy_url else "no",
    )

    # Configure proxy if available
    proxies = None
    if proxy_url:
        proxies = {"http://": proxy_url, "https://": proxy_url}

    # Execute request (follow redirects: shop.rewe.de → www.rewe.de)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20.0,
        proxies=proxies,
    ) as client:
        response = await client.get(SEARCH_API_URL, headers=headers, params=params)
        response.raise_for_status()

    # Parse response
    try:
        data = response.json()
    except Exception as e:
        raise ValueError(f"Non-JSON response from REWE API: {e}") from e

    # Extract products — handle HAL and legacy formats
    raw_products: list[dict] = (
        data.get("_embedded", {}).get("products")
        or data.get("products")
        or []
    )

    pag = data.get("pagination", {})
    pagination = {
        "page": pag.get("page", pag.get("currentPage", 1)),
        "totalPages": pag.get("totalPages", pag.get("pageCount", 1)),
        "totalResultCount": pag.get("totalResultCount", pag.get("objectCount", 0)),
    }

    logger.info(
        "REWE: %d results returned (%d total across %d pages)",
        len(raw_products),
        pagination["totalResultCount"],
        pagination["totalPages"],
    )

    products = [_parse_product(raw, i + 1) for i, raw in enumerate(raw_products)]
    return products, pagination
