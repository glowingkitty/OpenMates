# backend/apps/design/skills/search_icons_skill.py
#
# Icon search skill for the Design app.
# It searches Iconify server-side and returns metadata-only child embed payloads.
# SVG markup is intentionally fetched later through the authenticated OpenMates
# API route so clients never call Iconify or store raw SVG in embed content.

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.iconify.client import (
    IconifyClient,
    IconifyProviderError,
    IconifySearchProvider,
    is_valid_iconify_prefix,
)

logger = logging.getLogger(__name__)

MAX_PARALLEL_REQUESTS = 5
MAX_RESULTS_PER_REQUEST = 50
DEFAULT_RESULTS_PER_REQUEST = 24
SUPPORTED_LICENSE_POLICIES = {"permissive", "all"}


class IconSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None)
    query: str
    count: int = Field(default=DEFAULT_RESULTS_PER_REQUEST, ge=1, le=MAX_RESULTS_PER_REQUEST)
    license_policy: str = "permissive"
    include_prefixes: list[str] | None = None
    exclude_prefixes: list[str] | None = None


class IconSearchResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "design"
    skill_id: str = "search_icons"
    status: str = "finished"
    provider: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    warnings: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    ignore_fields_for_inference: list[str] = Field(default_factory=lambda: ["svg_path", "license_url", "author_url"])


class SearchIconsSkill(BaseSkill):
    """Search Iconify for SVG icons and return metadata-only child results."""

    async def execute(
        self,
        requests: list[dict[str, Any]] | None = None,
        provider_client: IconifySearchProvider | None = None,
        **kwargs: Any,
    ) -> IconSearchResponse:
        try:
            normalized_requests = self._normalize_requests(requests)
        except ValueError as exc:
            return IconSearchResponse(success=False, error=str(exc), error_code="invalid_request")

        provider = provider_client or IconifyClient()
        groups: list[dict[str, Any]] = []
        total_count = 0

        for index, request in enumerate(normalized_requests, start=1):
            request_id = request.id if request.id is not None else index
            try:
                results = await provider.search_icons(
                    request.query,
                    count=request.count,
                    license_policy=request.license_policy,
                    include_prefixes=request.include_prefixes,
                    exclude_prefixes=request.exclude_prefixes,
                )
            except IconifyProviderError as exc:
                return IconSearchResponse(
                    success=False,
                    provider=provider.provider_name,
                    error=exc.message,
                    error_code=exc.code,
                    warnings=[exc.as_warning()],
                )
            except Exception as exc:
                logger.error("design.search_icons failed: %s", exc, exc_info=True)
                return IconSearchResponse(success=False, provider=provider.provider_name, error=str(exc), error_code="search_failed")

            embed_results = [result.to_embed_payload() for result in results]
            groups.append(
                {
                    "id": request_id,
                    "query": request.query,
                    "provider": provider.provider_name,
                    "license_policy": request.license_policy,
                    "result_count": len(embed_results),
                    "empty_reason": "no_results" if not embed_results else None,
                    "results": embed_results,
                    "preview_results": embed_results[:6],
                }
            )
            total_count += len(embed_results)

        return IconSearchResponse(success=True, provider=provider.provider_name, results=groups, result_count=total_count)

    def _normalize_requests(self, requests: list[dict[str, Any]] | None) -> list[IconSearchRequestItem]:
        if not requests:
            raise ValueError("Icon search requires at least one request")
        if len(requests) > MAX_PARALLEL_REQUESTS:
            raise ValueError(f"Icon search supports at most {MAX_PARALLEL_REQUESTS} requests")

        normalized: list[IconSearchRequestItem] = []
        for raw_request in requests:
            try:
                item = IconSearchRequestItem.model_validate(raw_request)
            except ValidationError as exc:
                raise ValueError(str(exc)) from exc
            item.query = item.query.strip()
            if not item.query:
                raise ValueError("Icon search requires a query")
            item.license_policy = item.license_policy.strip().lower()
            if item.license_policy not in SUPPORTED_LICENSE_POLICIES:
                supported = ", ".join(sorted(SUPPORTED_LICENSE_POLICIES))
                raise ValueError(f"Unsupported icon license policy: {item.license_policy}. Supported values: {supported}")
            item.include_prefixes = self._normalize_prefixes(item.include_prefixes, field_name="include_prefixes")
            item.exclude_prefixes = self._normalize_prefixes(item.exclude_prefixes, field_name="exclude_prefixes")
            normalized.append(item)
        return normalized

    def _normalize_prefixes(self, prefixes: list[str] | None, *, field_name: str) -> list[str] | None:
        if prefixes is None:
            return None
        normalized: list[str] = []
        for prefix in prefixes:
            value = str(prefix).strip().lower()
            if not is_valid_iconify_prefix(value):
                raise ValueError(f"Invalid Iconify prefix in {field_name}: {prefix}")
            if value not in normalized:
                normalized.append(value)
        return normalized or None
