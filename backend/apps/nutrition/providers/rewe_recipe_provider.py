# backend/apps/nutrition/providers/rewe_recipe_provider.py
#
# REWE Online recipe provider — searches and fetches recipe data from rewe.de.
#
# Two-tier architecture:
#   1. SEARCH: Free JSON API at /api/recipe-filter/graphql (no auth, no proxy).
#      Returns recipe UIDs + titles matching category filters. Supports 7 filter
#      categories (diet, ingredient, effort, meal, dietary form, baking, occasion).
#
#   2. DETAIL: Firecrawl JSON extraction on individual recipe pages. REWE recipe
#      pages are server-rendered behind Cloudflare (residential proxies alone get
#      403). Firecrawl handles the JS challenge and returns structured JSON.
#      Results are cached in Directus (persistent) + Dragonfly (hot cache) to
#      minimize Firecrawl API calls.
#
# Discovered endpoints (reverse-engineered April 2026):
#   Filter API: GET https://www.rewe.de/api/recipe-filter/graphql
#               ?filterBy=should=<uid1>,<uid2>&must=<uid3>&pageNumber=1
#               → { data: { searchRecipeV2: { hits: { total, hits: [{_source: {recipe: {uid, title}}}] } } } }
#   Detail:     GET https://www.rewe.de/rezepte/{slug}/
#               → SSR HTML with recipe data (ingredients, instructions, nutrition, etc.)

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import httpx

from backend.shared.providers.firecrawl.firecrawl_scrape import (
    _get_firecrawl_api_key,
    FIRECRAWL_API_BASE_URL,
)

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Free recipe filter/search API — no auth required, bypasses Cloudflare
RECIPE_FILTER_API_URL = "https://www.rewe.de/api/recipe-filter/graphql"

# Recipe detail page base URL
RECIPE_PAGE_BASE = "https://www.rewe.de/rezepte"

# Dragonfly cache key prefix and TTL
CACHE_KEY_PREFIX = "rewe_recipe:"
CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days — recipes rarely change

# Maximum recipes per API page
RECIPES_PER_PAGE = 36

# Filter categories with their Contentstack UIDs (reverse-engineered April 2026).
# Operator "should" = OR matching, "must" = AND matching.
FILTER_TAGS: Dict[str, Dict[str, str]] = {
    # Ernährung (Diet type) — operator: should
    "fleisch": "blt8730c02b52d230da",
    "fisch": "blt5405d069773562ad",
    "vegetarisch": "blt9b23daf1b3ec8ce9",
    "vegan": "blte4a92c06b51fb6e6",
    # Hauptzutat (Main ingredient) — operator: should
    "nudeln": "blt151be870431c66dd",
    "pasta": "blt151be870431c66dd",
    "kartoffeln": "blt47763959e7e82287",
    "reis": "bltc1f7cd612fd230e0",
    "gemuese": "blt3a1003724d4733a0",
    "kuerbis": "blt35828d66cec870d6",
    # Aufwand (Effort) — operator: should
    "einfach": "blt066832a814b53341",
    "mittel": "blt9fd68021f10b2e93",
    "schwer": "blt30e1bbbd2df21d14",
    # Mahlzeit (Meal type) — operator: should
    "vorspeise": "blt1e1feba6de59e495",
    "hauptspeise": "blt66c6714997eb1078",
    "dessert": "bltb3d83ed2e3980caf",
    "beilagen": "blt9dbd1b3afda9fb8f",
    "fruehstueck": "blt37bf167d6270f000",
    "suppen": "blta45f7dbb84ba74a4",
    "auflauf": "blt06a311d377bd8e81",
    "snacks": "bltfacdc38867f5f70e",
    "getraenke": "blt7507de571376f432",
    # Ernährungsform (Dietary form) — operator: must
    "laktosefrei": "bltbbcbf53a640759f8",
    "low-carb": "blt07d21cfb663cc7e8",
    "glutenfrei": "blt62922669be122843",
    "paleo": "bltd38ab415bd11698b",
    "wenig-zucker": "blt06d801bc75fff980",
    "clean-eating": "bltb86d39e5572b3902",
    # Backen (Baking) — operator: should
    "kuchen": "blt05027b3a9a4b98ee",
    "torten": "blt729bcb7403edf2f6",
    "brot": "blt5b889b8769a38a92",
    "muffins": "blt5712e2b2cc1ca557",
    "cupcakes": "blta6d7cfcd3957561c",
    "plaetzchen": "blt60d857935d4cf4d9",
    # Anlässe (Occasions) — operator: should
    "fruehling": "blt3e76aaa11121ace6",
    "grillen": "bltc30657fa42bf1aff",
    "picknick": "bltc84bd6fa5eace568",
    "kindergerichte": "blt9e110ffd9af60ee1",
    "geburtstag": "blt3f3c5ece0964c21c",
    "guenstig": "blt5c388cf054c759c4",
    "party": "blte31548742ba6040e",
}

# Tags that use "must" operator (AND logic) — all others use "should" (OR)
MUST_OPERATOR_TAGS = {
    "laktosefrei", "low-carb", "glutenfrei", "paleo",
    "wenig-zucker", "clean-eating",
}

# JSON extraction schema for Firecrawl — defines what we extract from recipe pages
RECIPE_EXTRACT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "slug": {"type": "string"},
        "servings": {"type": "integer"},
        "prep_time_minutes": {"type": "integer"},
        "cook_time_minutes": {"type": "integer"},
        "total_time_minutes": {"type": "integer"},
        "difficulty": {"type": "string"},
        "rating": {"type": "number"},
        "rating_count": {"type": "integer"},
        "image_url": {"type": "string"},
        "recipe_url": {"type": "string"},
        "dietary_tags": {"type": "array", "items": {"type": "string"}},
        "categories": {"type": "array", "items": {"type": "string"}},
        "ernaehrwert_score": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string"},
                    "unit": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
        },
        "instructions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer"},
                    "text": {"type": "string"},
                },
            },
        },
        "nutrition": {
            "type": "object",
            "properties": {
                "calories_kcal": {"type": "number"},
                "protein_g": {"type": "number"},
                "fat_g": {"type": "number"},
                "carbs_g": {"type": "number"},
            },
        },
    },
}

RECIPE_EXTRACT_PROMPT = (
    "Extract ALL recipe data: title, description, slug (from URL), servings, "
    "prep_time_minutes, cook_time_minutes, total_time_minutes, difficulty, "
    "rating, rating_count, image_url, dietary_tags, categories, "
    "ernaehrwert_score, ingredients (amount, unit, name), "
    "instructions (step, text), nutrition (calories_kcal, protein_g, fat_g, carbs_g), "
    "recipe_url"
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class REWERecipe:
    """A single REWE recipe with full detail data."""

    # Identity
    uid: str
    title: str
    slug: str
    recipe_url: str
    image_url: Optional[str] = None
    description: Optional[str] = None

    # Timing
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    total_time_minutes: Optional[int] = None

    # Meta
    servings: Optional[int] = None
    difficulty: Optional[str] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    ernaehrwert_score: Optional[str] = None

    # Classification
    dietary_tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)

    # Content
    ingredients: List[Dict[str, str]] = field(default_factory=list)
    instructions: List[Dict[str, Any]] = field(default_factory=list)

    # Nutrition (per serving)
    nutrition: Optional[Dict[str, float]] = None

    # Search metadata
    search_rank: int = 0
    from_cache: bool = False

    def to_result_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict for skill responses."""
        d = asdict(self)
        d["type"] = "recipe"
        d["provider"] = "REWE"
        return d


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """
    Convert a recipe title to URL slug (REWE's kebab-case format).

    Expands German umlauts and replaces non-alphanumeric chars with hyphens.
    This is a best-effort approximation — the canonical slug comes from the API
    title which already matches the URL in most cases.
    """
    s = title.lower()
    for umlaut, rep in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        s = s.replace(umlaut, rep)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Filter API (free, no auth)
# ---------------------------------------------------------------------------


def _build_filter_param(filters: List[str]) -> str:
    """
    Build the filterBy query parameter from a list of filter tag names.

    Groups tags by operator (should/must) and joins them with &.
    Example: ["vegetarisch", "glutenfrei"] → "should=blt...&must=blt..."

    Args:
        filters: List of filter tag names (e.g. ["vegetarisch", "pasta", "glutenfrei"]).

    Returns:
        URL-safe filterBy value, or "empty" if no valid filters.
    """
    should_uids: List[str] = []
    must_uids: List[str] = []

    for tag in filters:
        tag_lower = tag.lower().strip()
        uid = FILTER_TAGS.get(tag_lower)
        if not uid:
            logger.warning("Unknown REWE recipe filter tag: %r (skipped)", tag)
            continue
        if tag_lower in MUST_OPERATOR_TAGS:
            must_uids.append(uid)
        else:
            should_uids.append(uid)

    parts: List[str] = []
    if should_uids:
        parts.append(f"should={','.join(should_uids)}")
    if must_uids:
        parts.append(f"must={','.join(must_uids)}")

    return "&".join(parts) if parts else "empty"


async def search_recipes_by_filter(
    filters: List[str],
    *,
    page: int = 1,
    max_results: int = 10,
) -> tuple[List[Dict[str, str]], int]:
    """
    Search REWE recipes using the free filter API.

    No authentication required. Returns recipe UIDs and titles only.

    Args:
        filters: List of filter tag names (e.g. ["vegetarisch", "pasta"]).
        page: Page number (1-indexed, 36 results per page).
        max_results: Maximum results to return (capped at page size).

    Returns:
        Tuple of (recipes_list, total_count) where each recipe is
        {"uid": "blt...", "title": "..."}.
    """
    filter_param = _build_filter_param(filters)

    params: Dict[str, Any] = {"filterBy": filter_param}
    if page > 1:
        params["pageNumber"] = page

    logger.info(
        "REWE recipe search: filters=%r page=%d filterBy=%s",
        filters, page, filter_param,
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            RECIPE_FILTER_API_URL,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()

    data = response.json()
    hits_data = data.get("data", {}).get("searchRecipeV2", {}).get("hits", {})
    total = hits_data.get("total", {}).get("value", 0)
    raw_hits = hits_data.get("hits", [])

    recipes = []
    for hit in raw_hits[:max_results]:
        recipe = hit.get("_source", {}).get("recipe", {})
        uid = recipe.get("uid", "")
        title = recipe.get("title", "")
        if uid and title:
            recipes.append({"uid": uid, "title": title, "slug": _slugify(title)})

    logger.info(
        "REWE recipe search: %d results (total=%d, page=%d)",
        len(recipes), total, page,
    )

    return recipes, total


# ---------------------------------------------------------------------------
# Recipe detail fetching via Firecrawl
# ---------------------------------------------------------------------------


async def _fetch_recipe_detail_firecrawl(
    slug: str,
    secrets_manager: "SecretsManager",
) -> Optional[Dict[str, Any]]:
    """
    Fetch full recipe data from a REWE recipe page using Firecrawl JSON extraction.

    Firecrawl handles the Cloudflare JS challenge and extracts structured JSON
    using the schema defined in RECIPE_EXTRACT_SCHEMA.

    Args:
        slug: Recipe URL slug (e.g. "butter-chicken").
        secrets_manager: SecretsManager for Firecrawl API key.

    Returns:
        Dict with extracted recipe data, or None on failure.
    """
    url = f"{RECIPE_PAGE_BASE}/{slug}/"

    api_key = await _get_firecrawl_api_key(secrets_manager)
    if not api_key:
        logger.error("Firecrawl API key not available for recipe detail fetch")
        return None

    payload = {
        "url": url,
        "formats": ["json"],
        "jsonOptions": {
            "prompt": RECIPE_EXTRACT_PROMPT,
            "schema": RECIPE_EXTRACT_SCHEMA,
        },
        "onlyMainContent": True,
        "location": {"country": "DE", "languages": ["de"]},
        "blockAds": True,
        "removeBase64Images": True,
        "storeInCache": True,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    endpoint = f"{FIRECRAWL_API_BASE_URL}/scrape"

    logger.info("Fetching REWE recipe detail via Firecrawl: slug=%s", slug)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()

        result = response.json()
        if not result.get("success"):
            logger.error("Firecrawl recipe scrape failed for %s: %s", slug, result)
            return None

        extracted = result.get("data", {}).get("json")
        if not extracted:
            logger.error("Firecrawl returned no JSON data for recipe %s", slug)
            return None

        # Ensure recipe_url is set
        if not extracted.get("recipe_url"):
            extracted["recipe_url"] = url
        if not extracted.get("slug"):
            extracted["slug"] = slug

        logger.info("Firecrawl recipe detail extracted: %s (%d ingredients)",
                     extracted.get("title", "?"), len(extracted.get("ingredients", [])))

        return extracted

    except httpx.HTTPStatusError as e:
        logger.error("Firecrawl HTTP error for recipe %s: %s", slug, e)
        return None
    except Exception as e:
        logger.error("Firecrawl error for recipe %s: %s", slug, e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Cache layer (Dragonfly hot cache + Directus persistent)
# ---------------------------------------------------------------------------


async def _get_cached_recipe(
    slug: str,
    cache_service: Optional[Any] = None,
    directus_service: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Look up cached recipe data. Checks Dragonfly first, then Directus.

    Args:
        slug: Recipe URL slug.
        cache_service: Optional Dragonfly cache service.
        directus_service: Optional Directus service for persistent cache.

    Returns:
        Cached recipe dict or None.
    """
    cache_key = f"{CACHE_KEY_PREFIX}{slug}"

    # 1. Try Dragonfly hot cache
    if cache_service:
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                data = json.loads(cached) if isinstance(cached, str) else cached
                logger.debug("REWE recipe cache hit (Dragonfly): %s", slug)
                return data
        except Exception as e:
            logger.warning("Dragonfly cache read error for recipe %s: %s", slug, e)

    # 2. Fall back to Directus persistent cache
    if directus_service:
        try:
            items = await directus_service.read_items(
                "recipe_cache",
                params={
                    "filter": {"slug": {"_eq": slug}, "provider": {"_eq": "rewe"}},
                    "limit": 1,
                },
            )
            if items and len(items) > 0:
                item = items[0]
                recipe_data = item.get("recipe_data")
                if recipe_data:
                    data = json.loads(recipe_data) if isinstance(recipe_data, str) else recipe_data
                    # Re-populate Dragonfly cache
                    if cache_service:
                        try:
                            await cache_service.set(
                                cache_key,
                                json.dumps(data, ensure_ascii=False),
                                ex=CACHE_TTL_SECONDS,
                            )
                        except Exception:
                            pass
                    logger.debug("REWE recipe cache hit (Directus): %s", slug)
                    return data
        except Exception as e:
            logger.warning("Directus cache read error for recipe %s: %s", slug, e)

    return None


async def _set_cached_recipe(
    slug: str,
    recipe_data: Dict[str, Any],
    cache_service: Optional[Any] = None,
    directus_service: Optional[Any] = None,
) -> None:
    """
    Store recipe data in both Dragonfly and Directus caches.

    Args:
        slug: Recipe URL slug.
        recipe_data: Full recipe data dict.
        cache_service: Optional Dragonfly cache service.
        directus_service: Optional Directus service for persistent cache.
    """
    cache_key = f"{CACHE_KEY_PREFIX}{slug}"
    data_json = json.dumps(recipe_data, ensure_ascii=False)

    # 1. Dragonfly hot cache
    if cache_service:
        try:
            await cache_service.set(cache_key, data_json, ex=CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning("Dragonfly cache write error for recipe %s: %s", slug, e)

    # 2. Directus persistent cache — upsert
    if directus_service:
        try:
            now = int(time.time())
            existing = await directus_service.read_items(
                "recipe_cache",
                params={
                    "filter": {"slug": {"_eq": slug}, "provider": {"_eq": "rewe"}},
                    "limit": 1,
                    "fields": ["id"],
                },
            )
            payload = {
                "slug": slug,
                "provider": "rewe",
                "title": recipe_data.get("title", ""),
                "recipe_data": data_json,
                "fetched_at": now,
            }
            if existing and len(existing) > 0:
                await directus_service.update_item(
                    "recipe_cache", existing[0]["id"], payload,
                )
            else:
                await directus_service.create_item("recipe_cache", payload)
        except Exception as e:
            logger.warning("Directus cache write error for recipe %s: %s", slug, e)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


async def fetch_recipe_details(
    recipes: List[Dict[str, str]],
    *,
    secrets_manager: "SecretsManager",
    cache_service: Optional[Any] = None,
    directus_service: Optional[Any] = None,
    max_results: int = 6,
) -> List[REWERecipe]:
    """
    Fetch full recipe details for a list of recipe stubs (uid + title + slug).

    Checks cache first, falls back to Firecrawl for cache misses. Results are
    cached in both Dragonfly (hot) and Directus (persistent).

    Args:
        recipes: List of {"uid": "...", "title": "...", "slug": "..."} dicts.
        secrets_manager: SecretsManager for Firecrawl API key.
        cache_service: Optional Dragonfly cache service.
        directus_service: Optional Directus service for persistent cache.
        max_results: Max recipes to fetch details for.

    Returns:
        List of REWERecipe objects with full detail data.
    """
    results: List[REWERecipe] = []

    for i, recipe_stub in enumerate(recipes[:max_results]):
        uid = recipe_stub.get("uid", "")
        title = recipe_stub.get("title", "")
        slug = recipe_stub.get("slug") or _slugify(title)

        # 1. Check cache
        cached_data = await _get_cached_recipe(
            slug, cache_service=cache_service, directus_service=directus_service,
        )

        if cached_data:
            recipe = REWERecipe(
                uid=uid,
                title=cached_data.get("title", title),
                slug=slug,
                recipe_url=cached_data.get("recipe_url", f"{RECIPE_PAGE_BASE}/{slug}/"),
                image_url=cached_data.get("image_url"),
                description=cached_data.get("description"),
                prep_time_minutes=cached_data.get("prep_time_minutes"),
                cook_time_minutes=cached_data.get("cook_time_minutes"),
                total_time_minutes=cached_data.get("total_time_minutes"),
                servings=cached_data.get("servings"),
                difficulty=cached_data.get("difficulty"),
                rating=cached_data.get("rating"),
                rating_count=cached_data.get("rating_count"),
                ernaehrwert_score=cached_data.get("ernaehrwert_score"),
                dietary_tags=cached_data.get("dietary_tags", []),
                categories=cached_data.get("categories", []),
                ingredients=cached_data.get("ingredients", []),
                instructions=cached_data.get("instructions", []),
                nutrition=cached_data.get("nutrition"),
                search_rank=i + 1,
                from_cache=True,
            )
            results.append(recipe)
            continue

        # 2. Fetch via Firecrawl
        detail = await _fetch_recipe_detail_firecrawl(slug, secrets_manager)
        if not detail:
            # Return minimal recipe with just title + URL
            results.append(REWERecipe(
                uid=uid,
                title=title,
                slug=slug,
                recipe_url=f"{RECIPE_PAGE_BASE}/{slug}/",
                search_rank=i + 1,
            ))
            continue

        # 3. Cache the result
        await _set_cached_recipe(
            slug, detail,
            cache_service=cache_service,
            directus_service=directus_service,
        )

        recipe = REWERecipe(
            uid=uid,
            title=detail.get("title", title),
            slug=slug,
            recipe_url=detail.get("recipe_url", f"{RECIPE_PAGE_BASE}/{slug}/"),
            image_url=detail.get("image_url"),
            description=detail.get("description"),
            prep_time_minutes=detail.get("prep_time_minutes"),
            cook_time_minutes=detail.get("cook_time_minutes"),
            total_time_minutes=detail.get("total_time_minutes"),
            servings=detail.get("servings"),
            difficulty=detail.get("difficulty"),
            rating=detail.get("rating"),
            rating_count=detail.get("rating_count"),
            ernaehrwert_score=detail.get("ernaehrwert_score"),
            dietary_tags=detail.get("dietary_tags", []),
            categories=detail.get("categories", []),
            ingredients=detail.get("ingredients", []),
            instructions=detail.get("instructions", []),
            nutrition=detail.get("nutrition"),
            search_rank=i + 1,
            from_cache=False,
        )
        results.append(recipe)

    return results
