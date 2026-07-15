"""3D model catalog search skill.

This read-only skill finds existing public 3D models and returns preview-only
child embed payloads. It deliberately links out to providers for downloads,
license details, purchases, and account-specific actions.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.models3d_catalogs import (
    Model3DProviderError,
    Model3DSearchProvider,
    MyMiniFactorySearchProvider,
    PrintablesSearchProvider,
    ThingiverseSearchProvider,
    collect_provider_search_results,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_KEYS = ("printables", "myminifactory", "thingiverse")
SUPPORTED_PROVIDER_ALIASES = {
    "all": "all",
    "printables": "printables",
    "printable": "printables",
    "myminifactory": "myminifactory",
    "my mini factory": "myminifactory",
    "thingiverse": "thingiverse",
}
SUPPORTED_SORTS = {"best_match", "popular", "downloads", "newest"}
MAX_PARALLEL_REQUESTS = 5
MAX_RESULTS_PER_REQUEST = 20
DEFAULT_RESULTS_PER_REQUEST = 10


class Model3DSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None)
    query: str
    providers: list[str] | None = None
    count: int = Field(default=DEFAULT_RESULTS_PER_REQUEST, ge=1, le=MAX_RESULTS_PER_REQUEST)
    sort: str = "best_match"
    free_only: bool | None = None


class Model3DSearchResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "models3d"
    skill_id: str = "search"
    status: str = "finished"
    provider: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    warnings: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    ignore_fields_for_inference: list[str] = Field(
        default_factory=lambda: [
            "preview_image_url",
            "thumbnail_url",
            "source_page_url",
            "normalized_provider_metadata",
        ]
    )


class SearchSkill(BaseSkill):
    """Search public 3D model catalogs and return preview-only child results."""

    async def execute(
        self,
        requests: list[dict[str, Any]] | None = None,
        provider_clients: dict[str, Model3DSearchProvider] | None = None,
        secrets_manager: SecretsManager | None = None,
        **kwargs: Any,
    ) -> Model3DSearchResponse:
        try:
            normalized_requests = self._normalize_requests(requests)
        except ValueError as exc:
            return Model3DSearchResponse(success=False, error=str(exc), error_code="invalid_request")

        all_groups: list[dict[str, Any]] = []
        all_warnings: list[dict[str, str]] = []
        total_count = 0
        provider_names: set[str] = set()

        for index, request in enumerate(normalized_requests, start=1):
            request_id = request.id if request.id is not None else index
            try:
                providers = await self._providers_for_request(
                    request.providers,
                    provider_clients=provider_clients,
                    secrets_manager=secrets_manager,
                )
                provider_names.update(provider.provider_name for provider in providers)
                results, warnings = await collect_provider_search_results(
                    query=request.query.strip(),
                    count=request.count,
                    providers=providers,
                )
                results = self._filter_and_sort_results(results, request)
                embed_results = [result.to_embed_payload() for result in results]
                all_groups.append(
                    {
                        "id": request_id,
                        "query": request.query.strip(),
                        "providers": [provider.provider_name for provider in providers],
                        "results": embed_results,
                        "result_count": len(embed_results),
                        "warnings": warnings,
                    }
                )
                all_warnings.extend(warnings)
                total_count += len(embed_results)
            except Model3DProviderError as exc:
                return Model3DSearchResponse(
                    success=False,
                    error=exc.message,
                    error_code=exc.code,
                    warnings=all_warnings or [exc.as_warning()],
                )
            except Exception as exc:
                logger.error("models3d.search failed: %s", exc, exc_info=True)
                return Model3DSearchResponse(success=False, error=str(exc), error_code="search_failed")

        return Model3DSearchResponse(
            success=True,
            provider=", ".join(sorted(provider_names)),
            results=all_groups,
            result_count=total_count,
            warnings=all_warnings,
        )

    def _normalize_requests(self, requests: list[dict[str, Any]] | None) -> list[Model3DSearchRequestItem]:
        if not requests:
            raise ValueError("3D model search requires at least one request")
        if len(requests) > MAX_PARALLEL_REQUESTS:
            raise ValueError(f"3D model search supports at most {MAX_PARALLEL_REQUESTS} requests")

        normalized: list[Model3DSearchRequestItem] = []
        for request in requests:
            item = Model3DSearchRequestItem.model_validate(request)
            item.query = item.query.strip()
            if not item.query:
                raise ValueError("3D model search requires a query")
            item.count = max(1, min(int(item.count or DEFAULT_RESULTS_PER_REQUEST), MAX_RESULTS_PER_REQUEST))
            item.sort = item.sort.strip().lower() if item.sort else "best_match"
            if item.sort not in SUPPORTED_SORTS:
                supported = ", ".join(sorted(SUPPORTED_SORTS))
                raise ValueError(f"Unsupported 3D model search sort: {item.sort}. Supported values: {supported}")
            normalized.append(item)
        return normalized

    def _filter_and_sort_results(
        self,
        results: list[Any],
        request: Model3DSearchRequestItem,
    ) -> list[Any]:
        filtered = [result for result in results if not request.free_only or result.is_free is True]

        if request.sort == "popular":
            filtered.sort(
                key=lambda result: (
                    result.likes_count or 0,
                    result.rating or 0,
                    result.download_count or 0,
                ),
                reverse=True,
            )
        elif request.sort == "downloads":
            filtered.sort(key=lambda result: result.download_count or 0, reverse=True)
        elif request.sort == "newest":
            filtered.sort(
                key=lambda result: str(
                    result.published_at
                    or result.created_at
                    or result.updated_at
                    or ""
                ),
                reverse=True,
            )

        return filtered[: request.count]

    async def _providers_for_request(
        self,
        requested_providers: list[str] | None,
        *,
        provider_clients: dict[str, Model3DSearchProvider] | None,
        secrets_manager: SecretsManager | None,
    ) -> list[Model3DSearchProvider]:
        provider_keys = self._provider_keys(requested_providers)
        providers: list[Model3DSearchProvider] = []
        for provider_key in provider_keys:
            if provider_clients and provider_key in provider_clients:
                providers.append(provider_clients[provider_key])
                continue
            providers.append(await self._create_provider(provider_key, secrets_manager=secrets_manager))
        return providers

    def _provider_keys(self, requested_providers: list[str] | None) -> list[str]:
        if not requested_providers:
            return list(DEFAULT_PROVIDER_KEYS)
        provider_keys: list[str] = []
        for provider in requested_providers:
            key = SUPPORTED_PROVIDER_ALIASES.get(str(provider).strip().lower())
            if not key:
                raise ValueError(f"Unsupported 3D model search provider: {provider}")
            if key == "all":
                for default_key in DEFAULT_PROVIDER_KEYS:
                    if default_key not in provider_keys:
                        provider_keys.append(default_key)
                continue
            if key not in provider_keys:
                provider_keys.append(key)
        return provider_keys

    async def _create_provider(
        self,
        provider_key: str,
        *,
        secrets_manager: SecretsManager | None,
    ) -> Model3DSearchProvider:
        if provider_key == "printables":
            return PrintablesSearchProvider()
        if provider_key == "thingiverse":
            return ThingiverseSearchProvider(api_key=await self._provider_api_key(secrets_manager, "thingiverse"))
        if provider_key == "myminifactory":
            return MyMiniFactorySearchProvider(api_key=await self._provider_api_key(secrets_manager, "myminifactory"))
        raise ValueError(f"Unsupported 3D model search provider: {provider_key}")

    async def _provider_api_key(self, secrets_manager: SecretsManager | None, provider_key: str) -> str | None:
        if secrets_manager is None:
            secrets_manager, error_response = await self._get_or_create_secrets_manager(
                secrets_manager=None,
                skill_name="Models3DSearchSkill",
                error_response_factory=lambda message: Model3DSearchResponse(success=False, error=message),
                logger=logger,
            )
            if error_response:
                return None
        try:
            return await secrets_manager.get_secret(f"kv/data/providers/{provider_key}", "api_key")
        except Exception as exc:
            logger.warning("Could not load %s API key: %s", provider_key, exc)
            return None
