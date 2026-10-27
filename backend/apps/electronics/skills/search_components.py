"""Search schemas and explicit unavailable capability boundary."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


ComponentCategory = Literal["power_converters"]

PowerSupplyType = Literal["dc", "ac"]

OptimizationGoal = Literal["balanced", "low_cost", "high_efficiency", "small_footprint"]


class SearchComponentsRequestItem(BaseModel):
    """A single electronics component search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating batched responses.",
    )
    category: ComponentCategory = Field(
        default="power_converters",
        description="Component category. Currently only 'power_converters' is supported.",
    )
    input_voltage_min: float = Field(
        description="Minimum input voltage in volts. For a fixed input, set min and max equal.",
    )
    input_voltage_max: float = Field(
        description="Maximum input voltage in volts. For a fixed input, set min and max equal.",
    )
    output_voltage: float = Field(description="Target output voltage in volts.")
    output_current_max: float = Field(description="Maximum output current in amps.")
    supply_type: PowerSupplyType = Field(
        default="dc",
        description="Input supply type: 'dc' for DC/DC or 'ac' for AC/DC.",
    )
    isolated: bool = Field(
        default=False,
        description="Whether the converter should be isolated.",
    )
    ambient_temp_c: float = Field(
        default=30,
        description="Maximum ambient temperature in degrees Celsius.",
    )
    optimization: OptimizationGoal = Field(
        default="balanced",
        description="Optimization goal: balanced, low_cost, high_efficiency, or small_footprint.",
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of component candidates to return (1-20).",
    )


class SearchComponentsResponse(BaseModel):
    """Response payload for component search."""

    results: List[Dict[str, Any]] = Field(default_factory=list)
    provider: str = Field(default="")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    error_code: str | None = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "solution_id",
            "device_id",
            "raw",
        ]
    )


class SearchComponentsSkill(BaseSkill):
    """Preserve the capability path while no permitted provider is configured."""

    async def execute(self, *args: Any, **kwargs: Any):
        return SearchComponentsResponse(
            error="No permitted provider is available for this capability.",
            error_code="provider_unavailable",
        )
