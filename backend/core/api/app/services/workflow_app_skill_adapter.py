# backend/core/api/app/services/workflow_app_skill_adapter.py
#
# Workflow app-skill execution adapter.
# Keeps the workflow runner independent from app-specific code while still
# dispatching real app skills through the in-process SkillRegistry.
# Produces stable output aliases for decisions and downstream actions.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from typing import Any


class WorkflowAppSkillAdapter:
    """Dispatch workflow app-skill nodes and normalize their workflow outputs."""

    def __init__(self, registry: Any | None = None) -> None:
        self.registry = registry

    async def execute(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        registry = self.registry
        if registry is None:
            from backend.core.api.app.services.skill_registry import get_global_registry

            registry = get_global_registry()
        raw_output = await registry.dispatch_skill(app_id, skill_id, request)
        if hasattr(raw_output, "model_dump"):
            raw_output = raw_output.model_dump(mode="json")
        if not isinstance(raw_output, dict):
            raw_output = {"result": raw_output}
        return _normalize_skill_output(app_id, skill_id, request, raw_output)


def _normalize_skill_output(
    app_id: str,
    skill_id: str,
    request: dict[str, Any],
    raw_output: dict[str, Any],
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "app_id": app_id,
        "skill_id": skill_id,
        "raw": raw_output,
    }
    if raw_output.get("error"):
        output["error"] = raw_output.get("error")

    if app_id == "weather" and skill_id == "forecast":
        first_day = _first_result(raw_output)
        location = raw_output.get("location") or {}
        location_name = location.get("name") or request.get("location") or "selected location"
        output.update(
            {
                "summary": f"Weather forecast for {location_name}",
                "location": location,
                "provider": raw_output.get("provider"),
                "days_requested": raw_output.get("days_requested"),
                "rain_probability": first_day.get("precipitation_probability_max_pct"),
                "max_temperature_c": first_day.get("temperature_max_c"),
                "humidity_avg_pct": first_day.get("relative_humidity_avg_pct"),
                "forecast_day": first_day,
            }
        )
        return output

    if app_id == "news" and skill_id == "search":
        requests = request.get("requests") or []
        queries = [item.get("query") for item in requests if isinstance(item, dict) and item.get("query")]
        result_groups = raw_output.get("results") if isinstance(raw_output.get("results"), list) else []
        result_count = sum(
            len(group.get("results") or [])
            for group in result_groups
            if isinstance(group, dict)
        )
        output.update(
            {
                "summary": "News search completed",
                "queries": queries,
                "result_count": result_count or len(result_groups) or max(len(queries), 1),
                "provider": raw_output.get("provider"),
            }
        )
        return output

    results = raw_output.get("results")
    output.update(
        {
            "summary": raw_output.get("summary") or f"{app_id}:{skill_id} completed",
            "result_count": len(results) if isinstance(results, list) else None,
            "provider": raw_output.get("provider"),
        }
    )
    return output


def _first_result(raw_output: dict[str, Any]) -> dict[str, Any]:
    results = raw_output.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return {}
