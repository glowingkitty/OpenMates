"""Region-scoped preliminary trademark searches with explicit coverage gaps."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.trademarks import TrademarkProviderError, USPTOTrademarkClient

logger = logging.getLogger(__name__)

REGION_SOURCES = {
    "US": "https://tmsearch.uspto.gov/",
    "EU": "https://www.tmdn.org/tmview/",
    "DE": "https://register.dpma.de/DPMAregister/marke/uebersicht",
    "WORLDWIDE": "https://www.wipo.int/en/web/global-brand-database",
}
SEARCH_LIMITATION = "Preliminary name search only. No results do not establish legal availability; unregistered rights and other jurisdictions may still matter. Spelling similarity is not a complete phonetic, visual or legal similarity assessment."


class TrademarkSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[StrictStr] = Field(min_length=1, max_length=3)
    regions: list[Literal["US", "EU", "DE", "WORLDWIDE"]] = Field(min_length=1, max_length=4)
    nice_classes: list[StrictInt] = Field(default_factory=list, max_length=10)
    status: Literal["active", "all"] = "active"
    match: Literal["exact", "similar"] = "similar"
    max_results: StrictInt = Field(default=10, ge=1, le=20)


class TrademarkSearchResponse(BaseModel):
    success: bool = False
    app_id: str = "business"
    skill_id: str = "search_trademarks"
    status: str = "finished"
    query: str = ""
    regions: list[str] = Field(default_factory=list)
    nice_classes: list[int] = Field(default_factory=list)
    status_filter: Literal["active", "all"] = "active"
    match: Literal["exact", "similar"] = "similar"
    provider: str = "USPTO"
    result_count: int = 0
    # Keep the entire response as one saved embed, including zero-match coverage.
    # A top-level results array would be flattened by the shared inference pipeline.
    matches: list[dict[str, Any]] = Field(default_factory=list)
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    partial: bool = False
    limitation: str = SEARCH_LIMITATION
    summary: str | None = None
    error: str | None = None
    error_code: str | None = None


class SearchTrademarksSkill(BaseSkill):
    """Only call a provider for the requested supported territory."""

    async def execute(
        self, queries: list[str] | None = None, regions: list[str] | None = None,
        nice_classes: list[int] | None = None, status: str = "active",
        match: str = "similar", max_results: int = 10,
        provider_client: USPTOTrademarkClient | None = None, **kwargs: Any,
    ) -> TrademarkSearchResponse:
        del kwargs
        try:
            request = TrademarkSearchRequest.model_validate({
                "queries": queries, "regions": regions, "nice_classes": nice_classes if nice_classes is not None else [],
                "status": status, "match": match, "max_results": max_results,
            })
            request.queries = list(dict.fromkeys(query.strip() for query in request.queries))
            if any(not query or len(query) > 120 or any(ord(char) < 32 for char in query) for query in request.queries):
                raise ValueError("Invalid name")
            if any(not 1 <= value <= 45 for value in request.nice_classes):
                raise ValueError("Invalid Nice class")
            request.regions = list(dict.fromkeys(request.regions))
            request.nice_classes = list(dict.fromkeys(request.nice_classes))
        except (ValidationError, ValueError):
            return TrademarkSearchResponse(
                error="Provide 1–3 nonblank names, explicit regions, valid Nice classes (1–45), and a result limit of 1–20.",
                error_code="invalid_request", status="error",
            )

        provider = provider_client or USPTOTrademarkClient()
        results: list[dict[str, Any]] = []
        coverage: list[dict[str, Any]] = []
        for query in request.queries:
            for region in request.regions:
                context = {"query": query, "region": region, "source_url": REGION_SOURCES[region], "match": request.match}
                if region != "US":
                    message = (
                        "EU searches require free approved EUIPO API access; national EU marks also require separate coverage." if region == "EU" else
                        "German national, EU and international rights need manual register checks; no permitted keyless provider is configured." if region == "DE" else
                        "Worldwide coverage is not configured. WIPO prohibits automatic queries; select supported target regions or search manually."
                    )
                    coverage.append({**context, "provider": None, "status": "unsupported", "error_code": "region_unsupported", "message": message})
                    continue
                try:
                    response = await provider.search(
                        query, nice_classes=request.nice_classes, status=request.status,
                        match=request.match, max_results=request.max_results,
                    )
                    results.extend(response["results"])
                    coverage.append({
                        **context, "provider": provider.provider_name,
                        "status": "partial" if response["partial"] else "searched",
                        "total_matches": response["total_matches"], "returned_count": len(response["results"]),
                        "more_results": response["more_results"], "checked_at": response["checked_at"],
                    })
                except TrademarkProviderError as exc:
                    coverage.append({**context, "provider": provider.provider_name, "status": "error", "error_code": exc.code, "message": exc.message})
                except Exception:
                    logger.error("Trademark provider raised an unexpected failure", exc_info=False)
                    coverage.append({**context, "provider": provider.provider_name, "status": "error", "error_code": "provider_unavailable", "message": "Trademark provider unavailable"})

        success = any(item["status"] in {"searched", "partial"} for item in coverage)
        partial = any(item["status"] != "searched" for item in coverage)
        return TrademarkSearchResponse(
            success=success, status="finished" if success else "error",
            query=", ".join(request.queries), regions=request.regions, matches=results,
            nice_classes=request.nice_classes, status_filter=request.status, match=request.match,
            result_count=len(results), coverage=coverage, partial=partial,
            summary=f"{len(results)} trademark records; coverage: " + ", ".join(f"{item['region']} {item['status']}" for item in coverage),
            error=None if success else "No requested region could be searched. See coverage for required setup or manual sources.",
            error_code=None if success else "search_unavailable",
        )

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        return {"query": ", ".join(str(value) for value in request.get("queries", [])), "regions": request.get("regions", []), "provider": "USPTO"}
