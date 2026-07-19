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

from backend.shared.python_utils.app_skill_output_safety import (
    AppSkillOutputSafetyContext,
    APP_SKILL_SURFACE_WORKFLOW,
    is_external_data_skill,
    sanitize_app_skill_output,
    strip_request_security_controls,
)


AI_APP_ID = "ai"
AI_ASK_SKILL_ID = "ask"
OPENAI_USER_ROLE = "user"


class WorkflowAppSkillAdapter:
    """Dispatch workflow app-skill nodes and normalize their workflow outputs."""

    def __init__(self, registry: Any | None = None, binding_revalidator: Any | None = None) -> None:
        self.registry = registry
        self.binding_revalidator = binding_revalidator

    async def revalidate_binding(self, binding_ref: Any, user_id: str, app_id: str, skill_id: str) -> None:
        """Require a runtime resolver to re-check opaque provider bindings."""
        if not isinstance(binding_ref, str) or not binding_ref:
            raise PermissionError("Workflow provider binding is invalid")
        if self.binding_revalidator is None:
            raise PermissionError("Workflow provider binding revalidation is unavailable")
        approved = await self.binding_revalidator.revalidate(binding_ref, user_id, app_id, skill_id)
        if approved is not True:
            raise PermissionError("Workflow provider binding is no longer authorized")

    async def execute(self, app_id: str, skill_id: str, request: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
        registry = self.registry
        if registry is None:
            from backend.core.api.app.services.skill_registry import get_global_registry

            registry = get_global_registry()
        request_without_security = strip_request_security_controls(request)
        skill_request = _prepare_workflow_skill_request(app_id, skill_id, request_without_security, user_id)
        raw_output = await registry.dispatch_skill(app_id, skill_id, skill_request)
        if hasattr(raw_output, "model_dump"):
            raw_output = raw_output.model_dump(mode="json")
        if not isinstance(raw_output, dict):
            raw_output = {"result": raw_output}
        metadata = registry.get_metadata(app_id) if hasattr(registry, "get_metadata") else None
        raw_output = await sanitize_app_skill_output(
            raw_output,
            AppSkillOutputSafetyContext(
                app_id=app_id,
                skill_id=skill_id,
                surface=APP_SKILL_SURFACE_WORKFLOW,
                request_body=request if isinstance(request, dict) else {},
                external_data=is_external_data_skill(metadata, app_id, skill_id),
                log_prefix=f"[WorkflowAppSkill {app_id}.{skill_id}] ",
            ),
        )
        return _normalize_skill_output(app_id, skill_id, skill_request, raw_output)


def _prepare_workflow_skill_request(app_id: str, skill_id: str, request: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    if app_id != AI_APP_ID or skill_id != AI_ASK_SKILL_ID:
        return request
    if "messages" in request:
        skill_request = dict(request)
    else:
        prompt = request.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return request
        skill_request = {key: value for key, value in request.items() if key != "prompt"}
        skill_request["messages"] = [{"role": OPENAI_USER_ROLE, "content": prompt}]
    if user_id:
        skill_request["_user_id"] = user_id
    skill_request["_external_request"] = True
    return skill_request


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
    artifact_ids = _collect_artifact_ids(raw_output)
    task_ids = _collect_string_values(raw_output, ("task_id", "task_ids", "job_id", "job_ids"))
    output.update(
        {
            "summary": raw_output.get("summary") or f"{app_id}:{skill_id} completed",
            "result_count": len(results) if isinstance(results, list) else None,
            "provider": raw_output.get("provider"),
        }
    )
    if artifact_ids:
        output["artifact_ids"] = artifact_ids
    if task_ids:
        output["task_ids"] = task_ids
    return output


def _first_result(raw_output: dict[str, Any]) -> dict[str, Any]:
    results = raw_output.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return {}


def _collect_artifact_ids(raw_output: dict[str, Any]) -> list[str]:
    return _collect_string_values(
        raw_output,
        (
            "artifact_id",
            "artifact_ids",
            "embed_id",
            "embed_ids",
            "file_id",
            "file_ids",
            "video_id",
            "video_ids",
        ),
    )


def _collect_string_values(raw_output: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = raw_output.get(key)
        if isinstance(value, str) and value:
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and item)
    return values
