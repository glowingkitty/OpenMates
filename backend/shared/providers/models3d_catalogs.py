"""Preview-only 3D model catalog provider helpers.

Architecture: `models3d.search` normalizes public catalog search results into
safe child embed payloads. V1 intentionally stores source links and preview
images only; it never downloads model files or executes provider viewers.
Provider credentials stay server-side and are never serialized into results.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Protocol
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field


DEFAULT_TIMEOUT_SECONDS = 15.0
PRINTABLES_GRAPHQL_URL = "https://api.printables.com/graphql/"
PRINTABLES_MEDIA_BASE_URL = "https://media.printables.com"
PRINTABLES_SOURCE_BASE_URL = "https://www.printables.com/model"
MYMINIFACTORY_SEARCH_URL = "https://www.myminifactory.com/api/v2/search"
THINGIVERSE_SEARCH_URL = "https://api.thingiverse.com/search/{query}"

FORBIDDEN_METADATA_KEYS = {
    "api_key",
    "access_token",
    "authorization",
    "bearer",
    "cookie",
    "download_url",
    "download_urls",
    "file_url",
    "file_urls",
    "fileuploads",
    "files",
    "files_url",
    "javascript",
    "script",
    "token",
}


class Model3DProviderError(Exception):
    """Typed provider error surfaced by the search skill."""

    def __init__(self, provider: str, code: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.message = message

    def as_warning(self) -> dict[str, str]:
        return {"provider": self.provider, "code": self.code, "message": self.message}


class Model3DProviderResult(BaseModel):
    """Normalized preview-only 3D model search result."""

    title: str
    provider: str
    provider_kind: str
    provider_item_id: str
    source_page_url: str
    preview_image_url: str | None = None
    thumbnail_url: str | None = None
    creator_name: str | None = None
    license: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    rating: float | None = None
    likes_count: int | None = None
    download_count: int | None = None
    files_count: int | None = None
    price: str | None = None
    is_free: bool | None = None
    normalized_provider_metadata: dict[str, Any] = Field(default_factory=dict)

    def to_embed_payload(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload["type"] = "model_result"
        payload["parent_app_skill_type"] = "app_skill_use"
        payload["open_cta_label"] = f"Open on {self.provider}"
        return payload


class Model3DSearchProvider(Protocol):
    provider_name: str

    async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]: ...


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tags_from(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = item.get("name") if isinstance(item, dict) else item
        if isinstance(tag, str) and tag.strip():
            tags.append(tag.strip())
    return tags[:12]


def _category_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _first_string(value.get("name"), value.get("title"))
    return _first_string(value)


def _safe_metadata(raw: dict[str, Any], allowed_keys: Iterable[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in allowed_keys:
        lower_key = key.lower()
        if lower_key in FORBIDDEN_METADATA_KEYS:
            continue
        value = raw.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            continue
        metadata[key] = value
    return metadata


def _absolute_printables_image_url(file_path: Any) -> str | None:
    path = _first_string(file_path)
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{PRINTABLES_MEDIA_BASE_URL}/{path.lstrip('/')}"


def _is_free_price(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    if isinstance(value, str):
        stripped = value.strip().replace("€", "").replace("$", "")
        try:
            return float(stripped) == 0.0
        except ValueError:
            return stripped.lower() in {"free", "0", "0.00"}
    return None


def normalize_printables_print(item: dict[str, Any]) -> Model3DProviderResult:
    provider_item_id = str(item.get("id") or "").strip()
    if not provider_item_id:
        raise Model3DProviderError("Printables", "invalid_result", "Printables result missing id")

    title = _first_string(item.get("name"), item.get("title")) or "Untitled 3D model"
    slug = _first_string(item.get("slug"))
    image = item.get("image") if isinstance(item.get("image"), dict) else {}
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    price = item.get("price")
    source_suffix = f"{provider_item_id}-{slug}" if slug else provider_item_id
    return Model3DProviderResult(
        title=title,
        provider="Printables",
        provider_kind="reverse_engineered_browser_api",
        provider_item_id=provider_item_id,
        source_page_url=f"{PRINTABLES_SOURCE_BASE_URL}/{source_suffix}",
        preview_image_url=_absolute_printables_image_url(image.get("filePath")),
        thumbnail_url=_absolute_printables_image_url(image.get("filePath")),
        creator_name=_first_string(user.get("publicUsername"), user.get("username"), user.get("name")),
        license=_category_name(item.get("license")),
        tags=_tags_from(item.get("tags")),
        category=_category_name(item.get("category")),
        rating=_float_or_none(item.get("ratingAvg")),
        likes_count=_int_or_none(item.get("likesCount")),
        download_count=_int_or_none(item.get("downloadCount")),
        files_count=_int_or_none(item.get("filesCount")),
        price=str(price) if price is not None else None,
        is_free=_is_free_price(price),
        normalized_provider_metadata=_safe_metadata(item, ("datePublished", "imagesCount")),
    )


def normalize_myminifactory_object(item: dict[str, Any]) -> Model3DProviderResult:
    provider_item_id = str(item.get("id") or item.get("objectId") or "").strip()
    if not provider_item_id:
        raise Model3DProviderError("MyMiniFactory", "invalid_result", "MyMiniFactory result missing id")

    designer = item.get("designer") if isinstance(item.get("designer"), dict) else {}
    price = item.get("price")
    return Model3DProviderResult(
        title=_first_string(item.get("name"), item.get("title")) or "Untitled 3D model",
        provider="MyMiniFactory",
        provider_kind="official_api",
        provider_item_id=provider_item_id,
        source_page_url=_first_string(item.get("url"), item.get("sourceUrl"))
        or f"https://www.myminifactory.com/object/{provider_item_id}",
        preview_image_url=_first_string(item.get("thumbnailUrl"), item.get("thumbnail_url"), item.get("imageUrl")),
        thumbnail_url=_first_string(item.get("thumbnailUrl"), item.get("thumbnail_url")),
        creator_name=_first_string(designer.get("username"), designer.get("name"), item.get("designerName")),
        license=_first_string(item.get("license"), item.get("licenseName")),
        tags=_tags_from(item.get("tags")),
        category=_category_name(item.get("category")),
        rating=_float_or_none(item.get("rating")),
        likes_count=_int_or_none(item.get("likes")),
        download_count=_int_or_none(item.get("downloads")),
        files_count=_int_or_none(item.get("filesCount")),
        price=str(price) if price is not None else None,
        is_free=_is_free_price(price),
        normalized_provider_metadata=_safe_metadata(item, ("publishedAt", "visibility")),
    )


def normalize_thingiverse_thing(item: dict[str, Any]) -> Model3DProviderResult:
    provider_item_id = str(item.get("id") or "").strip()
    if not provider_item_id:
        raise Model3DProviderError("Thingiverse", "invalid_result", "Thingiverse result missing id")

    creator = item.get("creator") if isinstance(item.get("creator"), dict) else {}
    return Model3DProviderResult(
        title=_first_string(item.get("name"), item.get("title")) or "Untitled 3D model",
        provider="Thingiverse",
        provider_kind="official_api",
        provider_item_id=provider_item_id,
        source_page_url=_first_string(item.get("public_url"), item.get("url"))
        or f"https://www.thingiverse.com/thing:{provider_item_id}",
        preview_image_url=_first_string(item.get("thumbnail"), item.get("preview_image_url"), item.get("image_url")),
        thumbnail_url=_first_string(item.get("thumbnail"), item.get("thumbnail_url")),
        creator_name=_first_string(creator.get("name"), creator.get("username"), item.get("creator_name")),
        license=_first_string(item.get("license")),
        tags=_tags_from(item.get("tags")),
        category=_category_name(item.get("category")),
        rating=_float_or_none(item.get("rating")),
        likes_count=_int_or_none(item.get("like_count"),),
        download_count=_int_or_none(item.get("download_count")),
        files_count=_int_or_none(item.get("file_count")),
        is_free=True,
        normalized_provider_metadata=_safe_metadata(item, ("added", "modified", "is_wip")),
    )


class PrintablesSearchProvider:
    provider_name = "Printables"

    async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
        graphql_query = """
        query SearchPrints($query: String!, $limit: Int!) {
          searchPrints2(query: $query, printType: print, limit: $limit, ordering: best_match) {
            items {
              id
              name
              slug
              datePublished
              likesCount
              downloadCount
              ratingAvg
              filesCount
              price
              user { publicUsername }
              image { filePath }
              license { name }
              category { name }
              tags { name }
            }
          }
        }
        """
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                PRINTABLES_GRAPHQL_URL,
                json={"query": graphql_query, "variables": {"query": query, "limit": count}},
            )
        if response.status_code != 200:
            raise Model3DProviderError("Printables", "http_error", f"Printables returned HTTP {response.status_code}")
        payload = response.json()
        if payload.get("errors"):
            raise Model3DProviderError("Printables", "graphql_error", "Printables GraphQL search failed")
        search_payload = payload.get("data", {}).get("searchPrints2") or {}
        items = search_payload.get("items") if isinstance(search_payload, dict) else search_payload
        items = items or []
        if not isinstance(items, list):
            raise Model3DProviderError("Printables", "invalid_response", "Printables returned an invalid search response")
        return [normalize_printables_print(item) for item in items if isinstance(item, dict)]


class MyMiniFactorySearchProvider:
    provider_name = "MyMiniFactory"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("MYMINIFACTORY_API_KEY") or "").strip()

    async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
        if not self.api_key:
            raise Model3DProviderError("MyMiniFactory", "missing_api_key", "Missing MyMiniFactory API key")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"q": query, "limit": count}
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(MYMINIFACTORY_SEARCH_URL, params=params, headers=headers)
        if response.status_code != 200:
            raise Model3DProviderError("MyMiniFactory", "http_error", f"MyMiniFactory returned HTTP {response.status_code}")
        payload = response.json()
        items = payload.get("results") or payload.get("items") or payload if isinstance(payload, list) else []
        if not isinstance(items, list):
            raise Model3DProviderError("MyMiniFactory", "invalid_response", "MyMiniFactory returned an invalid search response")
        return [normalize_myminifactory_object(item) for item in items if isinstance(item, dict)]


class ThingiverseSearchProvider:
    provider_name = "Thingiverse"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("THINGIVERSE_API_KEY") or "").strip()

    async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
        if not self.api_key:
            raise Model3DProviderError("Thingiverse", "missing_api_key", "Missing Thingiverse API key")
        url = THINGIVERSE_SEARCH_URL.format(query=quote_plus(query))
        params = {"type": "things", "per_page": count}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise Model3DProviderError("Thingiverse", "http_error", f"Thingiverse returned HTTP {response.status_code}")
        payload = response.json()
        items = payload.get("hits") or payload.get("results") or payload if isinstance(payload, list) else []
        if not isinstance(items, list):
            raise Model3DProviderError("Thingiverse", "invalid_response", "Thingiverse returned an invalid search response")
        return [normalize_thingiverse_thing(item) for item in items if isinstance(item, dict)]


async def collect_provider_search_results(
    *,
    query: str,
    count: int,
    providers: list[Model3DSearchProvider],
) -> tuple[list[Model3DProviderResult], list[dict[str, str]]]:
    results: list[Model3DProviderResult] = []
    warnings: list[dict[str, str]] = []
    for provider in providers:
        try:
            results.extend(await provider.search(query, count=count))
        except Model3DProviderError as exc:
            warnings.append(exc.as_warning())
        except Exception as exc:
            warnings.append(
                {
                    "provider": getattr(provider, "provider_name", provider.__class__.__name__),
                    "code": "provider_error",
                    "message": str(exc),
                }
            )

    if not results:
        raise Model3DProviderError("models3d", "all_providers_failed", "No 3D model search providers returned results")
    return results, warnings
