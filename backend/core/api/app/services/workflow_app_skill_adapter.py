# backend/core/api/app/services/workflow_app_skill_adapter.py
#
# Workflow app-skill execution adapter.
# Keeps the workflow runner independent from app-specific code while still
# dispatching real app skills through the in-process SkillRegistry.
# Produces stable output aliases for decisions and downstream actions.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import hashlib
from typing import Any
from datetime import datetime, timedelta
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.shared.python_utils.billing_utils import BillingError, ensure_credit_headroom
from backend.shared.python_utils.app_skill_output_safety import (
    AppSkillOutputSafetyContext,
    APP_SKILL_SURFACE_WORKFLOW,
    central_app_skill_dispatch,
    is_external_data_skill,
    sanitize_app_skill_output,
    strip_request_security_controls,
)


AI_APP_ID = "ai"
AI_ASK_SKILL_ID = "ask"
OPENAI_USER_ROLE = "user"
WORKFLOW_USAGE_SOURCES = frozenset({"workflow", "workflow_test"})


class WorkflowSkillBillingError(RuntimeError):
    """Typed, privacy-safe failure surfaced in workflow node history."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WorkflowAppSkillAdapter:
    """Dispatch workflow app-skill nodes and normalize their workflow outputs."""

    def __init__(
        self,
        registry: Any | None = None,
        binding_revalidator: Any | None = None,
        *,
        secrets_manager: Any | None = None,
        cache_service: Any | None = None,
    ) -> None:
        self.registry = registry
        self.binding_revalidator = binding_revalidator
        self.secrets_manager = secrets_manager
        self.cache_service = cache_service

    async def revalidate_binding(self, binding_ref: Any, user_id: str, app_id: str, skill_id: str) -> None:
        """Require a runtime resolver to re-check opaque provider bindings."""
        if not isinstance(binding_ref, str) or not binding_ref:
            raise PermissionError("Workflow provider binding is invalid")
        if self.binding_revalidator is None:
            raise PermissionError("Workflow provider binding revalidation is unavailable")
        approved = await self.binding_revalidator.revalidate(binding_ref, user_id, app_id, skill_id)
        if approved is not True:
            raise PermissionError("Workflow provider binding is no longer authorized")

    async def execute(
        self,
        app_id: str,
        skill_id: str,
        request: dict[str, Any],
        *,
        user_id: str | None = None,
        billing_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        registry = self.registry
        if registry is None:
            from backend.core.api.app.services.skill_registry import get_global_registry

            registry = get_global_registry()
        request_without_security = strip_request_security_controls(request)
        skill_request = _prepare_workflow_skill_request(
            app_id,
            skill_id,
            request_without_security,
            user_id,
        )
        metadata = registry.get_metadata(app_id) if hasattr(registry, "get_metadata") else None
        if billing_context and (app_id, skill_id) != (AI_APP_ID, AI_ASK_SKILL_ID):
            _workflow_usage_source(billing_context)
            _workflow_billing_identity(
                app_id=app_id,
                skill_id=skill_id,
                billing_context=billing_context,
                item_index=0,
            )
            await _precheck_workflow_skill_billing(
                app_id=app_id,
                skill_id=skill_id,
                request=skill_request,
                user_id=user_id,
                metadata=metadata,
            )
        with central_app_skill_dispatch():
            raw_output = await registry.dispatch_skill(app_id, skill_id, skill_request)
        if hasattr(raw_output, "model_dump"):
            raw_output = raw_output.model_dump(mode="json")
        if not isinstance(raw_output, dict):
            raw_output = {"result": raw_output}
        raw_output = await sanitize_app_skill_output(
            raw_output,
            AppSkillOutputSafetyContext(
                app_id=app_id,
                skill_id=skill_id,
                surface=APP_SKILL_SURFACE_WORKFLOW,
                request_body=request if isinstance(request, dict) else {},
                external_data=is_external_data_skill(metadata, app_id, skill_id),
                secrets_manager=self.secrets_manager,
                cache_service=self.cache_service,
                log_prefix=f"[WorkflowAppSkill {app_id}.{skill_id}] ",
            ),
        )
        # ai.ask settles actual token usage in its existing worker pipeline;
        # charging again here would double bill it.
        workflow_credit_cost = 0
        if billing_context and (app_id, skill_id) != (AI_APP_ID, AI_ASK_SKILL_ID):
            workflow_credit_cost = await _charge_workflow_skill_result(
                app_id=app_id,
                skill_id=skill_id,
                request=skill_request,
                result=raw_output,
                user_id=user_id,
                metadata=metadata,
                billing_context=billing_context,
            )
        output = _normalize_skill_output(app_id, skill_id, skill_request, raw_output)
        if billing_context:
            output["_workflow_credit_cost"] = workflow_credit_cost
        return output


def _prepare_workflow_skill_request(
    app_id: str,
    skill_id: str,
    request: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any]:
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


def _workflow_usage_source(billing_context: dict[str, Any]) -> str:
    source = billing_context.get("source")
    if source not in WORKFLOW_USAGE_SOURCES:
        raise WorkflowSkillBillingError("WORKFLOW_BILLING_INVALID_CONTEXT", "Workflow billing context is invalid")
    return str(source)


def _workflow_billing_identity(
    *,
    app_id: str,
    skill_id: str,
    billing_context: dict[str, Any],
    item_index: int,
) -> str:
    identity_parts = [
        billing_context.get("workflow_id"),
        billing_context.get("run_id"),
        billing_context.get("node_id"),
        app_id,
        skill_id,
        str(item_index),
    ]
    if not all(isinstance(value, str) and value for value in identity_parts):
        raise WorkflowSkillBillingError("WORKFLOW_BILLING_INVALID_CONTEXT", "Workflow billing context is invalid")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "openmates:workflow-billing:" + ":".join(identity_parts)))


def _find_skill_definition(metadata: Any, skill_id: str) -> Any | None:
    if metadata is None:
        return None
    return next((skill for skill in (getattr(metadata, "skills", None) or []) if skill.id == skill_id), None)


async def _precheck_workflow_skill_billing(
    *,
    app_id: str,
    skill_id: str,
    request: dict[str, Any],
    user_id: str | None,
    metadata: Any,
) -> None:
    if not user_id or metadata is None or _find_skill_definition(metadata, skill_id) is None:
        raise WorkflowSkillBillingError("WORKFLOW_BILLING_UNAVAILABLE", "Workflow skill billing is unavailable")

    from backend.core.api.app.routes import apps_api

    reserved_credits = apps_api.get_variable_preflight_reserved_credits(app_id, skill_id, request)
    estimated_credits = await apps_api.calculate_skill_credits(
        app_metadata=metadata,
        skill_id=skill_id,
        input_data=request,
        app_id=app_id,
    )
    try:
        await ensure_credit_headroom(
            user_id=user_id,
            estimated_credits=max(reserved_credits, estimated_credits),
            operation_name=f"workflow skill {app_id}.{skill_id}",
            log_prefix="[WorkflowBilling]",
        )
    except BillingError as exc:
        raise WorkflowSkillBillingError("INSUFFICIENT_CREDITS", "Insufficient credits for this workflow step") from exc


async def _charge_workflow_skill_result(
    *,
    app_id: str,
    skill_id: str,
    request: dict[str, Any],
    result: dict[str, Any],
    user_id: str | None,
    metadata: Any,
    billing_context: dict[str, Any],
) -> int:
    if not user_id or metadata is None:
        raise WorkflowSkillBillingError("WORKFLOW_BILLING_UNAVAILABLE", "Workflow skill billing is unavailable")

    from backend.core.api.app.routes import apps_api
    from backend.core.api.app.utils.config_manager import ConfigManager

    if not apps_api.is_skill_execution_successful(result):
        return 0
    credits_charged = await apps_api.calculate_skill_credits(
        app_metadata=metadata,
        skill_id=skill_id,
        input_data=request,
        result_data=result,
        app_id=app_id,
    )
    if credits_charged <= 0:
        return 0

    requests = request.get("requests")
    units_processed = len(requests) if isinstance(requests, list) else 1
    result_charge_items = apps_api.get_variable_result_charge_items(app_id, skill_id, result)
    if result_charge_items is None:
        per_request_credits = credits_charged // units_processed if units_processed > 0 else credits_charged
        credits_remainder = credits_charged - (per_request_credits * units_processed)
        charge_items = [
            (index, per_request_credits + (credits_remainder if index == units_processed - 1 else 0))
            for index in range(units_processed)
        ]
    else:
        charge_items = result_charge_items

    skill_definition = _find_skill_definition(metadata, skill_id)
    if skill_definition is None:
        raise WorkflowSkillBillingError("WORKFLOW_BILLING_UNAVAILABLE", "Workflow skill billing is unavailable")
    provider_info = apps_api.resolve_skill_provider_info(skill_definition, app_id, ConfigManager())
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    source = _workflow_usage_source(billing_context)

    charged_total = 0
    for item_index, item_credits in charge_items:
        if item_credits <= 0:
            continue
        operation_id = _workflow_billing_identity(
            app_id=app_id,
            skill_id=skill_id,
            billing_context=billing_context,
            item_index=item_index,
        )
        usage_details = {
            "source": source,
            "units_processed": 1,
            "model_used": provider_info["model_used"],
            "server_provider": provider_info["server_provider"],
            "server_region": provider_info["server_region"],
            "operation_id": operation_id,
        }
        usage_details.update(apps_api.get_variable_result_usage_details(app_id, skill_id, result, item_index))
        try:
            charge_result = await apps_api.charge_credits_via_internal_api(
                user_id=user_id,
                user_id_hash=user_id_hash,
                credits=item_credits,
                app_id=app_id,
                skill_id=skill_id,
                usage_details=usage_details,
                idempotency_key=operation_id,
                raise_on_error=True,
            )
            actual_credits = charge_result.get("charged_credits") if isinstance(charge_result, dict) else None
            if not isinstance(actual_credits, int) or actual_credits < 0:
                raise RuntimeError("Billing response did not include charged credits")
            charged_total += actual_credits
        except Exception as exc:
            response = getattr(exc, "response", None)
            code = "INSUFFICIENT_CREDITS" if getattr(response, "status_code", None) == 402 else "WORKFLOW_BILLING_UNAVAILABLE"
            message = "Insufficient credits for this workflow step" if code == "INSUFFICIENT_CREDITS" else "Workflow skill billing could not be completed"
            raise WorkflowSkillBillingError(code, message) from exc
    return charged_total


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
        days = [dict(day) for day in raw_output.get("results", []) if isinstance(day, dict)]
        first_day = days[0] if days else {}
        rain_periods = _rain_periods(first_day)
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
                "forecast_days": days,
                "results": days,
                "result_count": len(days),
                "hourly": first_day.get("hourly") or [],
                "rain_periods": rain_periods,
                "rain_expected": bool(rain_periods) if _has_rain_data(first_day) else None,
                "rain_summary": _rain_summary(rain_periods, first_day),
            }
        )
        return output

    if app_id in {"news", "events", "home"} and skill_id == "search":
        requests = request.get("requests") or []
        queries = [item.get("query") for item in requests if isinstance(item, dict) and item.get("query")]
        results = _search_results(raw_output)
        aliases = {"news": "articles", "events": "events", "home": "listings"}
        output.update({
            "summary": f"{app_id.capitalize()} search completed",
            "queries": queries,
            "results": results,
            aliases[app_id]: results,
            "result_count": len(results),
            "provider": raw_output.get("provider"),
            "warnings": raw_output.get("warnings") or [],
            "partial": bool(raw_output.get("warnings")),
        })
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


def _search_results(raw_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten request groups without exposing request IDs as result identities."""
    items: list[dict[str, Any]] = []
    for group in raw_output.get("results") or []:
        if not isinstance(group, dict):
            continue
        candidates = group.get("results") if isinstance(group.get("results"), list) else [group]
        for raw in candidates:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            url = item.get("url")
            if isinstance(url, str) and url:
                item["canonical_url"] = _canonical_url(url)
            provider = item.get("provider") or raw_output.get("provider")
            if provider:
                item["provider"] = provider
            identity = item.get("source_id") or item.get("id") or item.get("canonical_url")
            if identity is not None:
                item["source_id"] = str(identity)
            items.append(item)
    return items


def _canonical_url(value: str) -> str:
    """Remove transport fragments and known tracking keys, keeping semantic query parameters."""
    parts = urlsplit(value)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "msclkid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), ""))


def _rain_periods(day: dict[str, Any]) -> list[dict[str, Any]]:
    """Group contiguous hourly rain forecasts; absent numeric values remain unknown."""
    periods: list[dict[str, Any]] = []
    for hour in day.get("hourly") or []:
        if not isinstance(hour, dict):
            continue
        probability = hour.get("precipitation_probability_pct")
        amount = hour.get("precipitation_mm")
        condition = str(hour.get("condition") or "").lower()
        snow = condition in {"snow", "sleet"} or hour.get("weather_code") in {71, 73, 75, 77, 85, 86}
        rainy = not snow and ((isinstance(probability, (float, int)) and probability >= 50)
                             or (isinstance(amount, (float, int)) and amount > 0) or condition == "rain")
        if not rainy:
            continue
        timestamp = hour.get("timestamp")
        if not isinstance(timestamp, str):
            continue
        try:
            start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        end = start + timedelta(hours=1)
        if periods and periods[-1]["end"] == start.isoformat():
            periods[-1]["end"] = end.isoformat()
            periods[-1]["end_time"] = end.strftime("%H:%M")
            if isinstance(probability, (int, float)):
                periods[-1]["probability_pct"] = max(periods[-1]["probability_pct"] or 0, probability)
        else:
            periods.append({"start": start.isoformat(), "end": end.isoformat(),
                            "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M"),
                            "probability_pct": probability, "timezone": day.get("timezone")})
    return periods


def _rain_summary(periods: list[dict[str, Any]], day: dict[str, Any]) -> str:
    """Human-readable deterministic timing, without inference or invented forecast data."""
    if not _has_rain_data(day):
        return "Hourly rain timing is unavailable."
    if not periods:
        return "No rain is forecast today."
    times = ", ".join(f"{period['start_time']}–{period['end_time']}" for period in periods)
    zone = f" ({day['timezone']})" if day.get("timezone") else ""
    return f"Rain is forecast today: {times}{zone}."


def _has_rain_data(day: dict[str, Any]) -> bool:
    """Do not call missing hourly precipitation data a dry forecast."""
    return any(isinstance(hour, dict) and (
        isinstance(hour.get("precipitation_mm"), (int, float))
        or isinstance(hour.get("precipitation_probability_pct"), (int, float))
        or hour.get("condition") in {"dry", "rain", "snow", "sleet", "clear", "partly-cloudy", "cloudy"}
    ) for hour in day.get("hourly") or [])
