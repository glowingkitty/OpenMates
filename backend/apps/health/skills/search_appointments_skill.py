"""Appointment search contracts retained while no permitted source is available."""
from typing import Annotated, Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, StrictBool, StringConstraints, field_validator
from backend.apps.base_skill import BaseSkill

DEFAULT_MAX_DOCTORS = 10
FILTERED_SEARCH_MAX_DOCTORS = 30
UNAVAILABLE_ERROR = "Appointment search is unavailable: no permitted provider is configured."

class SearchAppointmentsRequestItem(BaseModel):
    """A single appointment search request."""

    id: Optional[str | int] = None
    max_doctors: int = Field(default=DEFAULT_MAX_DOCTORS, gt=0, le=FILTERED_SEARCH_MAX_DOCTORS, strict=True)

    speciality: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="Doctor speciality or type (e.g. 'augenarzt', 'hautarzt', 'zahnarzt', "
        "'ophthalmologist', 'dermatologist', 'general_practitioner', 'dentist', 'cardiologist')."
    )
    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="City where to search for appointments (e.g. 'Berlin', 'München', 'Munich', 'Hamburg')."
    )
    provider_platform: Optional[str] = Field(default=None, description="Optional source identifier; appointment search is currently unavailable.")
    insurance_sector: Optional[Literal["public", "private"]] = Field(
        default=None,
        description="Insurance type filter: 'public' (GKV) or 'private' (PKV). Omit for all types.",
    )
    telehealth: StrictBool = Field(
        default=False,
        description="If true, only return doctors offering telehealth (video consultation) appointments.",
    )
    language: Optional[str] = Field(
        default=None,
        description="Filter for doctors who speak a specific language (e.g. 'de', 'gb', 'ru', 'tr').",
    )
    days_ahead: Literal[1, 3, 7] = Field(
        default=7,
        description="Number of days ahead to look for availability.",
    )
    visit_motive_category: Optional[Literal["general", "checkup", "vaccination", "followup"]] = Field(
        default=None,
        description=(
            "Filter results by appointment type category. Supported categories: "
            "'general' (consultation, acute visit, new patient), "
            "'checkup' (preventive screening, health check), "
            "'vaccination' (immunisation), "
            "'followup' (follow-up, existing patient). "
            "When set, increases the doctor search pool and filters by visit motive "
            "name to return only relevant appointment types."
        ),
    )


    @field_validator("days_ahead", mode="before")
    @classmethod
    def normalize_lookahead_enum(cls, value: Any) -> Any:
        # The shared LLM schema adapter exposes numeric enums as strings for
        # Gemini. Restore only supported values before Literal validation.
        if isinstance(value, bool):
            raise ValueError("days_ahead must be a supported integer")
        if isinstance(value, str) and value in {"1", "3", "7"}:
            return int(value)
        return value


class SearchAppointmentsRequest(BaseModel):
    """Incoming request payload for the search_appointments skill."""

    requests: List[SearchAppointmentsRequestItem] = Field(
        description=(
            "Array of appointment search requests, each specifying the "
            "speciality, city, provider platform, and optional filters."
        )
    )


class SearchAppointmentsResponse(BaseModel):
    """
    Response payload for the search_appointments skill.

    Follows the standard OpenMates skill response structure with grouped results,
    provider info, suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="Unavailable")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "visit_motive_id",
            "agenda_id",
            "practice_id",
        ]
    )


class SearchAppointmentsSkill(BaseSkill):
    """Return an explicit unavailable result without contacting any service."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"provider": "Unavailable", "providers": []}

    async def execute(self, requests: List[Dict[str, Any]], secrets_manager: Any = None,
                      **kwargs: Any) -> SearchAppointmentsResponse:
        groups = [{"id": item.get("id", index + 1), "results": [], "error": UNAVAILABLE_ERROR}
                  for index, item in enumerate(requests or [])]
        return SearchAppointmentsResponse(results=groups, error=UNAVAILABLE_ERROR)
