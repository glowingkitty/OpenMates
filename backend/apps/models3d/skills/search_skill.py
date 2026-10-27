"""Search schemas and explicit unavailable capability boundary."""

from __future__ import annotations


from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


SUPPORTED_SORTS = {"best_match", "popular", "downloads", "newest"}

MAX_PARALLEL_REQUESTS = 5

MAX_RESULTS_PER_REQUEST = 20

DEFAULT_RESULTS_PER_REQUEST = 10


class Model3DSearchRequestItem(BaseModel):
    id: Any | None = Field(default=None)
    query: str
    providers: list[str] | None = None
    count: int = Field(
        default=DEFAULT_RESULTS_PER_REQUEST, ge=1, le=MAX_RESULTS_PER_REQUEST
    )
    sort: str = "best_match"
    free_only: bool | None = None
    relevance_criteria: str | None = Field(
        default=None,
        description=(
            "Optional natural-language model-selection goal used to rank a larger candidate pool. "
            "Omit it for a neutral search and never invent preferences."
        ),
    )


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
    """Preserve the capability path while no permitted provider is configured."""

    async def execute(self, *args: Any, **kwargs: Any):
        return Model3DSearchResponse(
            error="No permitted provider is available for this capability.",
            error_code="provider_unavailable",
        )
