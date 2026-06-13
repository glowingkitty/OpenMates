# backend/apps/nutrition/providers/edamam_recipe_provider.py
#
# Edamam Recipe Search provider for the Nutrition app.
# Wraps Recipe Search v2 with explicit field selection so the skill receives
# source links, images, ingredients, nutrition metadata, and instruction lines
# in one request page whenever possible. Recipes without instructions are
# intentionally filtered out before returning results.

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import parse_qsl, urlparse

import httpx

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

EDAMAM_API_URL = "https://api.edamam.com/api/recipes/v2"
EDAMAM_SECRET_PATH = "kv/data/providers/edamam"
EDAMAM_APP_ID_KEY = "app_id"
EDAMAM_APP_KEY_KEY = "app_key"

DEFAULT_MAX_RESULTS = 6
MAX_RESULTS = 10
MAX_PAGES = 3

RECIPE_FIELDS = [
    "uri",
    "label",
    "source",
    "url",
    "shareAs",
    "image",
    "images",
    "ingredientLines",
    "ingredients",
    "instructionLines",
    "yield",
    "totalTime",
    "calories",
    "dietLabels",
    "healthLabels",
    "cautions",
    "cuisineType",
    "mealType",
    "dishType",
    "totalNutrients",
    "totalDaily",
    "digest",
    "glycemicIndex",
    "inflammatoryIndex",
    "totalCO2Emissions",
    "co2EmissionsClass",
    "tags",
]

FILTER_LIST_PARAMS = {
    "diet",
    "health",
    "cuisineType",
    "mealType",
    "dishType",
    "excluded",
}

STEP_MARKER_RE = re.compile(r"(?:^|\s)(?:step\s+)?(\d+)\s*[:.)]\s*", re.IGNORECASE)


class EdamamProviderError(Exception):
    """Provider error with sanitized status context."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class EdamamRecipe:
    """A normalized Edamam recipe result for Nutrition embeds."""

    uid: str
    title: str
    recipe_url: str
    source: str
    image_url: Optional[str] = None
    images: Dict[str, Any] = field(default_factory=dict)
    share_url: Optional[str] = None
    servings: Optional[float] = None
    total_time_minutes: Optional[float] = None
    calories_total: Optional[float] = None
    calories_per_serving: Optional[float] = None
    ingredients: List[Dict[str, Any]] = field(default_factory=list)
    ingredient_lines: List[str] = field(default_factory=list)
    instructions: List[Dict[str, Any]] = field(default_factory=list)
    diet_labels: List[str] = field(default_factory=list)
    health_labels: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    cuisine_type: List[str] = field(default_factory=list)
    meal_type: List[str] = field(default_factory=list)
    dish_type: List[str] = field(default_factory=list)
    nutrition: Dict[str, Any] = field(default_factory=dict)
    total_daily: Dict[str, Any] = field(default_factory=dict)
    digest: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    glycemic_index: Optional[float] = None
    inflammatory_index: Optional[float] = None
    total_co2_emissions: Optional[float] = None
    co2_emissions_class: Optional[str] = None
    search_rank: int = 0

    def to_result_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["type"] = "recipe"
        result["provider"] = "Edamam"
        return result


@dataclass
class EdamamSearchResult:
    recipes: List[EdamamRecipe]
    total_available: int
    raw_hits_seen: int
    filtered_out_missing_instructions: int
    pages_requested: int

    def as_skill_payload(self) -> Dict[str, Any]:
        return {
            "recipes": [recipe.to_result_dict() for recipe in self.recipes],
            "total_available": self.total_available,
            "raw_hits_seen": self.raw_hits_seen,
            "filtered_out_missing_instructions": self.filtered_out_missing_instructions,
            "pages_requested": self.pages_requested,
        }


async def _get_edamam_credentials(secrets_manager: "SecretsManager") -> tuple[str, str]:
    app_id = None
    app_key = None
    try:
        app_id = await secrets_manager.get_secret(
            secret_path=EDAMAM_SECRET_PATH,
            secret_key=EDAMAM_APP_ID_KEY,
        )
        app_key = await secrets_manager.get_secret(
            secret_path=EDAMAM_SECRET_PATH,
            secret_key=EDAMAM_APP_KEY_KEY,
        )
    except Exception as exc:
        logger.debug("Failed to retrieve Edamam credentials from Vault: %s", exc)

    app_id = app_id or os.getenv("SECRET__EDAMAM__APP_ID")
    app_key = app_key or os.getenv("SECRET__EDAMAM__APP_KEY")
    if not app_id or not app_key:
        raise EdamamProviderError("Edamam credentials are not configured")
    return app_id, app_key


def normalize_instruction_lines(lines: List[str]) -> List[Dict[str, Any]]:
    """Normalize Edamam instruction lines into ordered step dictionaries."""
    steps: List[str] = []
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        matches = list(STEP_MARKER_RE.finditer(text))
        if len(matches) > 1:
            for index, match in enumerate(matches):
                start = match.end()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                segment = text[start:end].strip()
                if segment:
                    steps.append(segment)
            continue
        if len(matches) == 1 and matches[0].start() == 0:
            text = text[matches[0].end():].strip()
        if text:
            steps.append(text)

    return [{"step": index, "text": step} for index, step in enumerate(steps, start=1)]


def _best_image_url(recipe: Dict[str, Any]) -> Optional[str]:
    images = recipe.get("images") or {}
    for key in ("LARGE", "REGULAR", "SMALL", "THUMBNAIL"):
        value = images.get(key) or {}
        if value.get("url"):
            return value["url"]
    return recipe.get("image")


def _normalize_ingredients(recipe: Dict[str, Any]) -> List[Dict[str, Any]]:
    structured = recipe.get("ingredients") or []
    if structured:
        return [ingredient for ingredient in structured if isinstance(ingredient, dict)]
    return [{"text": line} for line in recipe.get("ingredientLines") or []]


def _calories_per_serving(recipe: Dict[str, Any]) -> Optional[float]:
    calories = recipe.get("calories")
    servings = recipe.get("yield")
    if isinstance(calories, (int, float)) and isinstance(servings, (int, float)) and servings > 0:
        return calories / servings
    return None


def _recipe_uid(recipe: Dict[str, Any]) -> str:
    uri = str(recipe.get("uri") or "").strip()
    if uri:
        return uri.rsplit("#", 1)[-1]
    url = str(recipe.get("url") or "").strip()
    if url:
        return url
    return str(recipe.get("label") or "recipe")


def _normalize_recipe(recipe: Dict[str, Any], *, search_rank: int) -> Optional[EdamamRecipe]:
    instruction_lines = recipe.get("instructionLines") or []
    instructions = normalize_instruction_lines(instruction_lines)
    if not instructions:
        return None

    title = str(recipe.get("label") or "").strip()
    recipe_url = str(recipe.get("url") or "").strip()
    if not title or not recipe_url:
        return None

    return EdamamRecipe(
        uid=_recipe_uid(recipe),
        title=title,
        recipe_url=recipe_url,
        source=str(recipe.get("source") or "Edamam").strip(),
        image_url=_best_image_url(recipe),
        images=recipe.get("images") or {},
        share_url=recipe.get("shareAs"),
        servings=recipe.get("yield"),
        total_time_minutes=recipe.get("totalTime"),
        calories_total=recipe.get("calories"),
        calories_per_serving=_calories_per_serving(recipe),
        ingredient_lines=recipe.get("ingredientLines") or [],
        ingredients=_normalize_ingredients(recipe),
        instructions=instructions,
        diet_labels=recipe.get("dietLabels") or [],
        health_labels=recipe.get("healthLabels") or [],
        cautions=recipe.get("cautions") or [],
        cuisine_type=recipe.get("cuisineType") or [],
        meal_type=recipe.get("mealType") or [],
        dish_type=recipe.get("dishType") or [],
        nutrition=recipe.get("totalNutrients") or {},
        total_daily=recipe.get("totalDaily") or {},
        digest=recipe.get("digest") or [],
        tags=recipe.get("tags") or [],
        glycemic_index=recipe.get("glycemicIndex"),
        inflammatory_index=recipe.get("inflammatoryIndex"),
        total_co2_emissions=recipe.get("totalCO2Emissions"),
        co2_emissions_class=recipe.get("co2EmissionsClass"),
        search_rank=search_rank,
    )


def _append_list_params(params: Dict[str, Any], name: str, value: Optional[List[str]]) -> None:
    if value:
        params[name] = [str(item).strip() for item in value if str(item).strip()]


def _build_search_params(
    *,
    query: str,
    app_id: str,
    app_key: str,
    diet: Optional[List[str]] = None,
    health: Optional[List[str]] = None,
    cuisine_type: Optional[List[str]] = None,
    meal_type: Optional[List[str]] = None,
    dish_type: Optional[List[str]] = None,
    excluded: Optional[List[str]] = None,
    time: Optional[str] = None,
    calories: Optional[str] = None,
    ingredients: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "type": "public",
        "q": query,
        "app_id": app_id,
        "app_key": app_key,
        "field": list(RECIPE_FIELDS),
    }
    _append_list_params(params, "diet", diet)
    _append_list_params(params, "health", health)
    _append_list_params(params, "cuisineType", cuisine_type)
    _append_list_params(params, "mealType", meal_type)
    _append_list_params(params, "dishType", dish_type)
    _append_list_params(params, "excluded", excluded)
    if time:
        params["time"] = time
    if calories:
        params["calories"] = calories
    if ingredients:
        params["ingr"] = ingredients
    return params


def _params_from_next_url(next_url: str, *, app_id: str, app_key: str) -> Dict[str, Any]:
    parsed = urlparse(next_url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    params: Dict[str, Any] = {}
    for key, value in pairs:
        if key in FILTER_LIST_PARAMS or key == "field":
            params.setdefault(key, []).append(value)
        else:
            params[key] = value
    params["app_id"] = app_id
    params["app_key"] = app_key
    existing_fields = set(params.get("field") or [])
    missing_fields = [field_name for field_name in RECIPE_FIELDS if field_name not in existing_fields]
    params.setdefault("field", [])
    params["field"].extend(missing_fields)
    return params


async def search_recipes(
    *,
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    secrets_manager: "SecretsManager",
    diet: Optional[List[str]] = None,
    health: Optional[List[str]] = None,
    cuisine_type: Optional[List[str]] = None,
    meal_type: Optional[List[str]] = None,
    dish_type: Optional[List[str]] = None,
    excluded: Optional[List[str]] = None,
    time: Optional[str] = None,
    calories: Optional[str] = None,
    ingredients: Optional[str] = None,
    max_pages: int = MAX_PAGES,
) -> EdamamSearchResult:
    """Search Edamam and return only recipes with usable instructions."""
    query = query.strip()
    if not query:
        raise EdamamProviderError("Recipe search query is required")

    max_results = min(MAX_RESULTS, max(1, int(max_results)))
    app_id, app_key = await _get_edamam_credentials(secrets_manager)
    params = _build_search_params(
        query=query,
        app_id=app_id,
        app_key=app_key,
        diet=diet,
        health=health,
        cuisine_type=cuisine_type,
        meal_type=meal_type,
        dish_type=dish_type,
        excluded=excluded,
        time=time,
        calories=calories,
        ingredients=ingredients,
    )

    recipes: List[EdamamRecipe] = []
    seen_keys: set[str] = set()
    raw_hits_seen = 0
    filtered_out_missing_instructions = 0
    pages_requested = 0
    total_available = 0
    next_url: Optional[str] = EDAMAM_API_URL

    async with httpx.AsyncClient(timeout=20.0) as client:
        while next_url and pages_requested < max_pages and len(recipes) < max_results:
            try:
                response = await client.get(
                    EDAMAM_API_URL,
                    params=params,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 429:
                    raise EdamamProviderError("Edamam rate limit exceeded", status_code=429) from exc
                if status_code in {401, 403}:
                    raise EdamamProviderError("Edamam credentials are invalid or unauthorized", status_code=status_code) from exc
                raise EdamamProviderError(f"Edamam request failed with HTTP {status_code}", status_code=status_code) from exc
            except httpx.HTTPError as exc:
                raise EdamamProviderError(f"Edamam request failed: {exc}") from exc

            pages_requested += 1
            data = response.json()
            total_available = int(data.get("count") or total_available or 0)
            hits = data.get("hits") or []
            raw_hits_seen += len(hits)

            for hit in hits:
                recipe_data = hit.get("recipe") or {}
                normalized = _normalize_recipe(recipe_data, search_rank=raw_hits_seen)
                if not normalized:
                    filtered_out_missing_instructions += 1
                    continue
                dedupe_key = (normalized.recipe_url or normalized.uid or normalized.title).lower()
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                recipes.append(normalized)
                if len(recipes) >= max_results:
                    break

            next_href = (data.get("_links") or {}).get("next", {}).get("href")
            next_url = next_href if next_href and len(recipes) < max_results else None
            if next_url:
                params = _params_from_next_url(next_url, app_id=app_id, app_key=app_key)

    logger.info(
        "Edamam recipe search query=%r returned=%d raw_hits=%d filtered_no_steps=%d pages=%d total=%d",
        query,
        len(recipes),
        raw_hits_seen,
        filtered_out_missing_instructions,
        pages_requested,
        total_available,
    )

    return EdamamSearchResult(
        recipes=recipes,
        total_available=total_available,
        raw_hits_seen=raw_hits_seen,
        filtered_out_missing_instructions=filtered_out_missing_instructions,
        pages_requested=pages_requested,
    )
