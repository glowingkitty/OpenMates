"""Product search contract, unavailable until an authorized provider is configured."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from backend.apps.base_skill import BaseSkill


class SearchProductsRequestItem(BaseModel):
    query: str
    provider: Optional[str] = None
    category: Optional[str] = None
    country: Optional[str] = None
    max_results: int = Field(default=10, ge=1, le=20)
    relevance_criteria: Optional[str] = Field(default=None, max_length=1000)
    reference_images: Optional[List[str]] = Field(default=None, max_length=3)
    sort: str = "relevance"
    service_type: Optional[str] = None
    department: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None


class SearchProductsRequest(BaseModel):
    requests: List[SearchProductsRequestItem]


class SearchProductsResponse(BaseModel):
    results: List[Dict[str, Any]] = Field(default_factory=list)
    provider: str = ""
    providers: List[str] = Field(default_factory=list)
    provider_required: bool = True
    available: bool = False
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(default_factory=lambda: [
        "type", "product_id", "image_url", "image_urls", "category_ids", "order_limit", "search_rank",
    ])


class SearchProductsSkill(BaseSkill):
    """Preserve the result contract without attempting any provider access."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"provider": "", "providers": [], "provider_required": True, "available": False}

    async def execute(self, requests: List[Dict[str, Any]], **kwargs: Any) -> SearchProductsResponse:
        message = "Product search is unavailable: no authorized provider is configured."
        groups = [
            {"id": request.get("id", index), "results": [], "error": message}
            for index, request in enumerate(requests or [])
            if isinstance(request, dict)
        ]
        return SearchProductsResponse(results=groups, error=message)
