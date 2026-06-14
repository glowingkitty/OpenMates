"""
SearchComponentsSkill — find electronic components and reference designs.

Architecture: docs/architecture/apps/app-skills.md

The first supported category is power_converters backed by the reverse-
engineered TI WEBENCH Power Designer solution search. The skill returns
component candidates with product links, performance summaries, and follow-up
actions for schematic/BOM retrieval.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.ti_webench import (
    TIWebenchPowerSearchRequest,
    search_power_solutions,
)

logger = logging.getLogger(__name__)


ComponentCategory = Literal["power_converters"]
PowerSupplyType = Literal["dc", "ac"]
OptimizationGoal = Literal["balanced", "low_cost", "high_efficiency", "small_footprint"]

OPTIMIZATION_TO_WEBENCH = {
    "small_footprint": 1,
    "low_cost": 2,
    "balanced": 3,
    "high_efficiency": 4,
}


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
    provider: str = Field(default="TI WEBENCH")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "solution_id",
            "device_id",
            "raw",
        ]
    )


class SearchComponentsSkill(BaseSkill):
    """Search electronics component providers for matching parts."""

    FOLLOW_UP_SUGGESTIONS = [
        "Compare by efficiency and BOM cost",
        "Show the TI product pages for these parts",
        "Get the WEBENCH schematic and BOM for the best result",
        "Generate a starter atopile module from the recommended design",
    ]

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> SearchComponentsResponse:
        """Execute batched component searches."""
        validated_requests, invalid_grouped_results, validation_errors, validation_error = self._partition_requests_by_required_fields(
            requests=requests,
            required_fields=[],
            field_display_names={},
            empty_error_message="No component search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchComponentsResponse(results=[], error=validation_error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=SearchComponentsResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider="TI WEBENCH",
                suggestions=self.FOLLOW_UP_SUGGESTIONS,
                logger=logger,
            )

        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchComponentsSkill",
            logger=logger,
        )
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=requests,
            logger=logger,
        )
        grouped_results = self._merge_grouped_results_preserving_request_order(
            grouped_results,
            invalid_grouped_results,
            requests,
        )

        return self._build_response_with_errors(
            response_class=SearchComponentsResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="TI WEBENCH",
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
        )

    async def _process_single_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        **kwargs: Any,
    ) -> tuple:
        """Process one component search request."""
        try:
            parsed = SearchComponentsRequestItem.model_validate(req)
        except Exception as exc:
            return (request_id, [], f"Invalid component search request: {exc}")

        if parsed.category != "power_converters":
            return (request_id, [], "Only category 'power_converters' is supported today")

        if parsed.input_voltage_min > parsed.input_voltage_max:
            return (request_id, [], "input_voltage_min must be <= input_voltage_max")

        if parsed.output_current_max <= 0 or parsed.output_voltage == 0:
            return (request_id, [], "output_voltage and output_current_max must be non-zero")

        max_results = max(1, min(20, parsed.max_results))
        webench_request = TIWebenchPowerSearchRequest(
            vinMin=parsed.input_voltage_min,
            vinMax=parsed.input_voltage_max,
            vout=[parsed.output_voltage],
            iout=[parsed.output_current_max],
            ambientTemp=parsed.ambient_temp_c,
            isIsolated=parsed.isolated,
            powerSupply=parsed.supply_type,
            optimizationSetting=OPTIMIZATION_TO_WEBENCH[parsed.optimization],
        )

        try:
            solutions = await search_power_solutions(
                webench_request,
                max_results=max_results,
            )
        except Exception as exc:
            logger.error("TI WEBENCH search failed: %s", exc, exc_info=True)
            return (request_id, [], f"TI WEBENCH search failed: {exc}")

        results = [self._format_solution(solution) for solution in solutions]
        return (request_id, results, None)

    def _format_solution(self, solution: Any) -> Dict[str, Any]:
        """Convert a WEBENCH solution into OpenMates-facing result data."""
        info = solution.info
        device = info.device
        base_part_number = device.basePn or device.partNumber
        product_slug = base_part_number.upper()
        efficiency_percent = (
            round(info.efficiency * 100, 2) if info.efficiency is not None else None
        )

        return {
            "type": "power_converter",
            "provider": "TI WEBENCH",
            "solution_id": solution.id,
            "rank": solution.rank,
            "part_number": device.partNumber,
            "base_part_number": base_part_number,
            "device_id": device.deviceId,
            "title": f"{device.partNumber} {info.topology or device.topology or 'power converter'}",
            "description": solution.considerations,
            "product_url": f"https://www.ti.com/product/{product_slug}",
            "datasheet_url": f"https://www.ti.com/lit/gpn/{product_slug.lower()}",
            "topology": info.topology or device.topology,
            "package": device.package,
            "regulator_type": device.regType,
            "control_mode": device.controlModeName,
            "price_usd": device.price,
            "bom_cost_usd": info.bomCost,
            "bom_count": info.bomCount,
            "efficiency_percent": efficiency_percent,
            "footprint_mm2": info.footprint,
            "frequency_hz": info.frequency,
            "temperature_c": info.temperature,
            "max_output_current_a": info.maxIout or device.ioutMax,
            "output_ripple_vpp": info.vOutPkPk,
            "input_voltage_min_v": device.vinMin,
            "input_voltage_max_v": device.vinMax,
            "output_voltage_min_v": device.voutMin,
            "output_voltage_max_v": device.voutMax,
            "isolated": device.isolated == "Y",
            "features": {
                "automotive": device.isAutomotive,
                "enable_pin": device.isEnablePin,
                "power_good": device.isPowerGood,
                "soft_start": device.isSoftStart,
                "external_sync": device.isExtSync,
                "light_load": device.isLightLoad,
                "synchronous_switch": device.isSyncSwitch,
            },
        }
