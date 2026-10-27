"""Unavailable capability; no authorized product-data provider is configured."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from backend.apps.base_skill import BaseSkill

class SearchStaysRequestItem(BaseModel):
    """A single accommodation search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: str = Field(
        description="Search query describing the destination or property "
        "(e.g. 'Hotels in Paris', 'Hostels near Eiffel Tower', 'Barcelona beachfront hotel')."
    )
    check_in_date: str = Field(description="Check-in date in YYYY-MM-DD format (e.g. '2026-03-15').")
    check_out_date: str = Field(description="Check-out date in YYYY-MM-DD format (e.g. '2026-03-18').")
    adults: int = Field(default=2, description="Number of adult guests.")
    children: int = Field(default=0, description="Number of children.")
    currency: str = Field(default="EUR", description="Price currency (ISO 4217 code, e.g. 'EUR', 'USD').")
    sort_by: str = Field(
        default="relevance",
        description="Sort order for results. Options: 'relevance' (default), 'price_asc', 'rating_desc', 'reviews_desc'.",
    )
    min_price: Optional[float] = Field(default=None, description="Minimum nightly price filter.")
    max_price: Optional[float] = Field(default=None, description="Maximum nightly price filter.")
    hotel_class: Optional[str] = Field(
        default=None,
        description="Comma-separated star rating filter (e.g. '3,4,5' for 3-star and above).",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum number of results to return (1-20).",
    )
    relevance_criteria: Optional[str] = Field(
        default=None,
        max_length=1_000,
        description="Optional natural-language stay goal used only to rank matching properties.",
    )

class SearchStaysRequest(BaseModel):
    """Incoming request payload for the search_stays skill."""

    requests: List[SearchStaysRequestItem] = Field(
        description="Array of stay search requests. Each request searches for "
        "accommodation at a specific destination for given dates."
    )

class SearchStaysResponse(BaseModel):
    """
    Response payload for the search_stays skill.

    Follows the standard OpenMates skill response structure with grouped results,
    provider info, suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="")
    providers: List[str] = Field(default_factory=list)
    provider_required: bool = True
    available: bool = False
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: ["property_token", "images", "nearby_places"]
    )

class SearchStaysSkill(BaseSkill):
    """Preserve the skill contract while the capability is unavailable."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"provider": "", "providers": [], "provider_required": True, "available": False}

    async def execute(self, requests: List[Dict[str, Any]], **kwargs: Any) -> SearchStaysResponse:
        message = "This capability is unavailable: no authorized provider is configured."
        groups = [
            {"id": request.get("id", index), "results": [], "error": message}
            for index, request in enumerate(requests or [])
            if isinstance(request, dict)
        ]
        return SearchStaysResponse(results=groups, error=message)
