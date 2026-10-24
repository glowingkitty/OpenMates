"""Generic catalog result contracts; no catalog provider is configured."""

from __future__ import annotations


from typing import Any, Protocol

from pydantic import BaseModel, Field


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
    description: str | None = None
    preview_image_url: str | None = None
    thumbnail_url: str | None = None
    creator_name: str | None = None
    published_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
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
        return payload


class Model3DSearchProvider(Protocol):
    provider_name: str

    async def search(
        self, query: str, *, count: int
    ) -> list[Model3DProviderResult]: ...


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
                    "provider": getattr(
                        provider, "provider_name", provider.__class__.__name__
                    ),
                    "code": "provider_error",
                    "message": str(exc),
                }
            )

    if not results:
        raise Model3DProviderError(
            "models3d",
            "all_providers_failed",
            "No 3D model search providers returned results",
        )
    return results, warnings
