# backend/shared/providers/iconify/client.py
#
# Pure Iconify API wrapper used by the Design app.
# It normalizes public icon metadata and fetches SVG markup server-side only.
# Clients receive OpenMates API paths, not Iconify URLs, so browser/native render
# paths do not leak user IP or client metadata to Iconify.

from __future__ import annotations

import html
import re
from typing import Any, Protocol
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, Field


ICONIFY_API_BASE_URL = "https://api.iconify.design"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_ICONIFY_RESULTS = 50
PREFIX_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ICON_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
URL_REFERENCE_PATTERN = re.compile(r"url\(\s*(['\"]?)(?:https?:|//|data:|javascript:)", re.IGNORECASE)
FORBIDDEN_SVG_TAGS = {"script", "foreignobject"}
REFERENCE_ATTRIBUTES = {"href", "xlink:href"}
PERMISSIVE_LICENSES = {
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0",
    "cc0-1.0",
    "isc",
    "mit",
    "ofl",
    "ofl-1.1",
    "open font license",
    "sil open font license 1.1",
    "unlicense",
}

ElementTree.register_namespace("", "http://www.w3.org/2000/svg")


class IconifyProviderError(Exception):
    """Typed provider error surfaced by Design icon search and SVG routes."""

    def __init__(self, provider: str, code: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.message = message

    def as_warning(self) -> dict[str, str]:
        return {"provider": self.provider, "code": self.code, "message": self.message}


class IconifyIconResult(BaseModel):
    """Normalized metadata-only Iconify icon result."""

    icon_id: str
    prefix: str
    name: str
    display_name: str
    collection_name: str | None = None
    collection_category: str | None = None
    license_title: str | None = None
    license_spdx: str | None = None
    license_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    width: int | None = None
    height: int | None = None
    palette: bool = False
    svg_path: str
    tags: list[str] = Field(default_factory=list)

    def to_embed_payload(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload["type"] = "icon_result"
        payload["parent_app_skill_type"] = "app_skill_use"
        return payload


class IconifySearchProvider(Protocol):
    provider_name: str

    async def search_icons(
        self,
        query: str,
        *,
        count: int,
        license_policy: str,
        include_prefixes: list[str] | None = None,
        exclude_prefixes: list[str] | None = None,
    ) -> list[IconifyIconResult]: ...


def is_valid_iconify_prefix(prefix: str) -> bool:
    return bool(PREFIX_PATTERN.fullmatch(prefix.strip()))


def is_valid_iconify_name(name: str) -> bool:
    return bool(ICON_NAME_PATTERN.fullmatch(name.strip()))


def is_permissive_license(spdx_or_title: str | None) -> bool:
    if not spdx_or_title:
        return False
    normalized = spdx_or_title.strip().lower()
    if normalized in PERMISSIVE_LICENSES:
        return True
    return normalized.startswith("bsd-")


def sanitize_iconify_svg(svg: str) -> str:
    """Remove harmless event attributes and reject active/external SVG content."""
    if not isinstance(svg, str) or "<svg" not in svg[:200].lower():
        raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned non-SVG content")
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned invalid SVG XML") from exc

    if _local_xml_name(root.tag) != "svg":
        raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned non-SVG XML")

    for element in root.iter():
        if _local_xml_name(element.tag) in FORBIDDEN_SVG_TAGS:
            raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned unsafe SVG content")
        for attribute_name, raw_value in list(element.attrib.items()):
            local_attribute = _local_xml_name(attribute_name)
            decoded_value = html.unescape(str(raw_value)).strip()
            if local_attribute.startswith("on"):
                del element.attrib[attribute_name]
                continue
            if local_attribute in REFERENCE_ATTRIBUTES and _is_external_reference(decoded_value):
                raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned unsafe SVG external references")
            if URL_REFERENCE_PATTERN.search(decoded_value):
                raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned unsafe SVG external references")

    return ElementTree.tostring(root, encoding="unicode")


def _local_xml_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def _is_external_reference(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http:", "https:", "//", "data:", "javascript:"))


def _display_name(icon_name: str) -> str:
    return " ".join(part.capitalize() for part in icon_name.replace("_", "-").split("-") if part) or icon_name


def _collection_info(collections: dict[str, Any], prefix: str) -> dict[str, Any]:
    info = collections.get(prefix)
    return info if isinstance(info, dict) else {}


def _license_info(collection: dict[str, Any]) -> dict[str, Any]:
    license_info = collection.get("license")
    return license_info if isinstance(license_info, dict) else {}


def _icon_metadata(icon_sets: dict[str, dict[str, Any]], prefix: str, name: str) -> dict[str, Any]:
    icon_set = icon_sets.get(prefix) or {}
    icons = icon_set.get("icons") if isinstance(icon_set.get("icons"), dict) else {}
    aliases = icon_set.get("aliases") if isinstance(icon_set.get("aliases"), dict) else {}
    metadata = icons.get(name) or aliases.get(name)
    return metadata if isinstance(metadata, dict) else {}


class IconifyClient:
    """Small async client for Iconify search, metadata, and SVG fetch endpoints."""

    provider_name = "Iconify"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, base_url: str = ICONIFY_API_BASE_URL) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")

    async def search_icons(
        self,
        query: str,
        *,
        count: int = 24,
        license_policy: str = "permissive",
        include_prefixes: list[str] | None = None,
        exclude_prefixes: list[str] | None = None,
    ) -> list[IconifyIconResult]:
        query = query.strip()
        if not query:
            raise IconifyProviderError("Iconify", "invalid_request", "Iconify search requires a query")
        count = max(1, min(int(count), MAX_ICONIFY_RESULTS))
        if license_policy not in {"permissive", "all"}:
            raise IconifyProviderError("Iconify", "invalid_request", f"Unsupported license policy: {license_policy}")

        include = {prefix.strip() for prefix in include_prefixes or [] if prefix.strip()}
        exclude = {prefix.strip() for prefix in exclude_prefixes or [] if prefix.strip()}

        data = await self._get_json("/search", params={"query": query, "limit": str(count)})
        icon_ids = [icon_id for icon_id in data.get("icons", []) if isinstance(icon_id, str) and ":" in icon_id]
        collections = data.get("collections") if isinstance(data.get("collections"), dict) else {}

        parsed: list[tuple[str, str]] = []
        for icon_id in icon_ids:
            prefix, name = icon_id.split(":", 1)
            if not is_valid_iconify_prefix(prefix) or not is_valid_iconify_name(name):
                continue
            if include and prefix not in include:
                continue
            if prefix in exclude:
                continue
            collection = _collection_info(collections, prefix)
            license_info = _license_info(collection)
            license_token = license_info.get("spdx") or license_info.get("title")
            if license_policy == "permissive" and not is_permissive_license(str(license_token) if license_token else None):
                continue
            parsed.append((prefix, name))

        icon_sets = await self._fetch_icon_sets(parsed)
        results: list[IconifyIconResult] = []
        for prefix, name in parsed:
            collection = _collection_info(collections, prefix)
            license_info = _license_info(collection)
            metadata = _icon_metadata(icon_sets, prefix, name)
            results.append(
                IconifyIconResult(
                    icon_id=f"{prefix}:{name}",
                    prefix=prefix,
                    name=name,
                    display_name=_display_name(name),
                    collection_name=collection.get("name") or prefix,
                    collection_category=collection.get("category"),
                    license_title=license_info.get("title"),
                    license_spdx=license_info.get("spdx"),
                    license_url=license_info.get("url"),
                    author_name=collection.get("author", {}).get("name") if isinstance(collection.get("author"), dict) else None,
                    author_url=collection.get("author", {}).get("url") if isinstance(collection.get("author"), dict) else None,
                    width=metadata.get("width"),
                    height=metadata.get("height"),
                    palette=bool(metadata.get("palette")),
                    svg_path=f"/v1/apps/design/icons/iconify/{prefix}/{name}.svg",
                    tags=list(metadata.get("tags") or [])[:12] if isinstance(metadata.get("tags"), list) else [],
                )
            )
        return results[:count]

    async def fetch_svg(self, prefix: str, name: str) -> str:
        if not is_valid_iconify_prefix(prefix) or not is_valid_iconify_name(name):
            raise IconifyProviderError("Iconify", "invalid_request", "Invalid Iconify icon identifier")
        response = await self._request("GET", f"/{prefix}/{name}.svg", params={"height": "24"})
        if response.status_code == 404:
            raise IconifyProviderError("Iconify", "icon_not_found", "Iconify icon not found")
        if response.status_code >= 500:
            raise IconifyProviderError("Iconify", "provider_unavailable", f"Iconify returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise IconifyProviderError("Iconify", "provider_error", f"Iconify returned HTTP {response.status_code}")
        return sanitize_iconify_svg(response.text)

    async def _fetch_icon_sets(self, icons: list[tuple[str, str]]) -> dict[str, dict[str, Any]]:
        names_by_prefix: dict[str, list[str]] = {}
        for prefix, name in icons:
            names_by_prefix.setdefault(prefix, []).append(name)

        icon_sets: dict[str, dict[str, Any]] = {}
        for prefix, names in names_by_prefix.items():
            icon_sets[prefix] = await self._get_json(f"/{prefix}.json", params={"icons": ",".join(names)})
        return icon_sets

    async def _get_json(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        response = await self._request("GET", path, params=params)
        if response.status_code >= 500:
            raise IconifyProviderError("Iconify", "provider_unavailable", f"Iconify returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise IconifyProviderError("Iconify", "provider_error", f"Iconify returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise IconifyProviderError("Iconify", "invalid_response", "Iconify returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise IconifyProviderError("Iconify", "invalid_response", "Iconify returned non-object JSON")
        return data

    async def _request(self, method: str, path: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(method, f"{self._base_url}{path}", params=params)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.request(method, f"{self._base_url}{path}", params=params)
