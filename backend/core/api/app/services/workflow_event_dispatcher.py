"""
Normalized Workflow event dispatch adapter.

Payload evaluation is transient and caller-supplied. Durable receipt and run
creation are delegated to the atomic Directus endpoint with no event payload.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService


class WorkflowEventDispatcher:
    """Accepts only owner- and project-scoped normalized Workflow events."""

    def __init__(self, runtime_service: WorkflowRuntimeService) -> None:
        self._runtime_service = runtime_service

    async def dispatch(
        self,
        trigger: Mapping[str, Any],
        event: Mapping[str, Any],
        predicate_matches: Callable[[Mapping[str, Any]], bool],
    ) -> dict[str, Any]:
        required = ("hashed_user_id", "hashed_project_id", "source", "event_type")
        if not trigger.get("enabled") or any(trigger.get(key) != event.get(key) for key in required):
            return {"accepted": False, "reason": "event_trigger_mismatch"}
        payload = event.get("payload")
        if not isinstance(payload, Mapping) or not predicate_matches(payload):
            return {"accepted": False, "reason": "predicate_not_matched"}

        fields = ("trigger_id", "event_id", "hashed_user_id", "hashed_project_id", "source", "event_type")
        data = {"trigger_id": trigger.get("trigger_id")}
        data.update({field: event.get(field) for field in fields if field != "trigger_id"})
        if any(not isinstance(value, str) or not value for value in data.values()):
            return {"accepted": False, "reason": "invalid_event"}
        return await self._runtime_service.execute("accept_event_trigger", data)
