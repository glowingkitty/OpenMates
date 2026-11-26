"""Appointment search contracts retained while no permitted source is available."""
from typing import Annotated, Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, StrictBool, StringConstraints, field_validator
from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS,
    rank_search_candidates,
)

MAX_RANKED_APPOINTMENTS = 20
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
    provider_platform: Optional[str] = Field(default=None, description="Optional identifier of an installed appointment source.")
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
    days_ahead: Literal[1, 3, 7, 30, 60] = Field(
        default=7,
        description="Availability window in days. Use 30 or 60 only when requested.",
    )
    requires_prescribing_clinician: StrictBool = Field(
        default=False,
        description="True for visits to discuss medication with a prescribing clinician.",
    )
    medication_visit: Optional[Literal["initiation", "continuation"]] = Field(
        default=None,
        description="Whether the visit should discuss starting or continuing medication.",
    )
    requires_external_diagnosis_acceptance: StrictBool = Field(
        default=False,
        description="True when the appointment must accept an existing diagnosis from another practice.",
    )
    relevance_criteria: Optional[Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_RELEVANCE_CRITERIA_CHARS,
    )]] = Field(
        default=None,
        description="Optional appointment requirements for ranking. Exclude names, identifiers and personal history.",
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
        if isinstance(value, str) and value in {"1", "3", "7", "30", "60"}:
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

    @staticmethod
    async def postprocess_installed_group(
        group: Dict[str, Any], request: Dict[str, Any], secrets_manager: Any,
        policy: Optional[InternalLlmPolicy],
    ) -> None:
        """Keep booking evidence intact and rank against optional requirements."""
        results = group["results"]
        medication_visit = request.get("medication_visit")
        requires_existing_diagnosis = request.get("requires_external_diagnosis_acceptance", False)
        requires_prescriber = bool(medication_visit or request.get("requires_prescribing_clinician"))
        if requires_prescriber or requires_existing_diagnosis:
            eligible = []
            for item in results:
                prescribing = item.get("prescribing_availability")
                scope = item.get("prescribing_scope")
                accepts_diagnosis = item.get("accepts_external_diagnosis")
                if requires_prescriber and (
                    prescribing == "unavailable"
                    or item.get("practitioner_role") == "non_prescribing"
                    or (medication_visit and scope in ("initiation", "continuation") and scope != medication_visit)
                ):
                    continue
                if requires_existing_diagnosis and accepts_diagnosis is False:
                    continue
                if requires_prescriber:
                    confirmed = prescribing == "available" and (
                        not medication_visit or scope in (medication_visit, "both")
                    ) and (not requires_existing_diagnosis or accepts_diagnosis is True)
                    item["prescribing_match"] = "confirmed" if confirmed else "unverified"
                if requires_existing_diagnosis:
                    item["external_diagnosis_match"] = "confirmed" if accepts_diagnosis is True else "unverified"
                eligible.append(item)
            group["excluded_appointment_count"] = len(results) - len(eligible)
            results = eligible
            group["results"] = results

        criteria = request.get("relevance_criteria")
        if criteria and len(results) > 1:
            candidates = results[:MAX_RANKED_APPOINTMENTS]
            ranking = await rank_search_candidates(
                candidates=candidates,
                candidate_projections=[{
                    field: item.get(field) for field in (
                        "speciality", "practitioner_role", "visit_motive", "service_name",
                        "insurance", "allows_new_patients", "telehealth", "languages",
                        "prescribing_availability", "prescribing_scope", "prescribing_match",
                        "accepts_external_diagnosis", "eligibility_notes",
                        "slot_datetime", "price", "appointment_duration_minutes",
                    ) if item.get(field) is not None
                } for item in candidates],
                relevance_criteria=criteria,
                search_parameters={
                    "prescribing_required": requires_prescriber,
                    "medication_visit": medication_visit,
                    "external_diagnosis_acceptance_required": requires_existing_diagnosis,
                },
                profile="health_appointments",
                secrets_manager=secrets_manager,
                policy=policy,
            )
            group["results"] = [*ranking.candidates, *results[MAX_RANKED_APPOINTMENTS:]]
            group["relevance_ranking"] = "applied" if ranking.applied else "unavailable"

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"provider": "Unavailable", "providers": []}

    async def execute(self, requests: List[Dict[str, Any]], secrets_manager: Any = None,
                      **kwargs: Any) -> SearchAppointmentsResponse:
        groups = [{"id": item.get("id", index + 1), "results": [], "error": UNAVAILABLE_ERROR}
                  for index, item in enumerate(requests or [])]
        return SearchAppointmentsResponse(results=groups, error=UNAVAILABLE_ERROR)
