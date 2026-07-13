"""
Atomic scheduler executor for accepted Workflow trigger occurrences.

This service does not select due triggers or retain recurrence plaintext. It
uses the Directus transaction endpoint to claim and fence one occurrence before
decrypting its schedule reference or invoking any workflow side effect.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService


class WorkflowSchedulerService:
    """Runs a single due trigger through the durable claim/start/advance protocol."""

    def __init__(self, runtime_service: WorkflowRuntimeService) -> None:
        self._runtime_service = runtime_service

    async def scan_due_triggers(
        self,
        *,
        now: int,
        dispatch_trigger: Callable[[str], Awaitable[Any]],
        limit: int = 100,
    ) -> dict[str, Any]:
        """Find indexed due trigger IDs and dispatch each to the fenced executor."""
        if limit <= 0:
            raise ValueError("Workflow due scanner limit must be positive")
        result = await self._runtime_service.execute("list_due_triggers", {"now": now, "limit": limit})
        trigger_ids = result.get("trigger_ids")
        if not isinstance(trigger_ids, list):
            raise RuntimeError("Workflow due scanner returned invalid trigger_ids")
        dispatched: list[str] = []
        for trigger_id in trigger_ids:
            if not isinstance(trigger_id, str) or not trigger_id:
                continue
            await dispatch_trigger(trigger_id)
            dispatched.append(trigger_id)
        return {"checked": len(trigger_ids), "dispatched": len(dispatched), "trigger_ids": dispatched}

    async def execute_due_trigger(
        self,
        trigger_id: str,
        decrypt_and_schedule: Callable[[str, str], Awaitable[int]],
        execute_run: Callable[[str, str, str, str], Awaitable[Any]],
    ) -> dict[str, Any]:
        claim = await self._runtime_service.execute("claim_due_trigger", {"trigger_id": trigger_id})
        run_id = claim.get("run_id")
        if not claim.get("accepted"):
            return {"accepted": False, "run_id": run_id}

        workflow_id = self._required_string(claim, "workflow_id")
        version_id = self._required_string(claim, "version_id")
        owner_user_id = self._required_string(claim, "owner_user_id")
        claim_token = self._required_string(claim, "claim_token")
        blob_ref = self._required_string(claim, "encrypted_schedule_config_ref")
        claim_generation = self._required_integer(claim, "claim_generation")
        run_id = self._required_string(claim, "run_id")

        # Recurrence plaintext is accessed only after the durable claim succeeds.
        next_run_at = await decrypt_and_schedule(owner_user_id, blob_ref)
        if not isinstance(next_run_at, int) or next_run_at <= 0:
            raise ValueError("Decrypted workflow recurrence returned an invalid next_run_at")

        started = await self._runtime_service.execute(
            "start_claimed_run",
            {
                "trigger_id": trigger_id,
                "run_id": run_id,
                "claim_generation": claim_generation,
                "claim_token": claim_token,
            },
        )
        if not started.get("started"):
            status = started.get("status")
            if status not in {"cancellation_requested", "cancelled"}:
                return {"accepted": False, "run_id": run_id}
            await self._runtime_service.execute(
                "advance_claimed_trigger",
                {
                    "trigger_id": trigger_id,
                    "claim_generation": claim_generation,
                    "claim_token": claim_token,
                    "next_run_at": next_run_at,
                },
            )
            return {"accepted": True, "run_id": run_id, "status": status, "next_run_at": next_run_at}

        await execute_run(run_id, workflow_id, version_id, owner_user_id)
        await self._runtime_service.execute(
            "advance_claimed_trigger",
            {
                "trigger_id": trigger_id,
                "claim_generation": claim_generation,
                "claim_token": claim_token,
                "next_run_at": next_run_at,
            },
        )
        return {"accepted": True, "run_id": run_id, "next_run_at": next_run_at}

    @staticmethod
    def next_run_at_from_schedule(schedule_config: Any, now: int | None = None) -> int:
        """Calculate the next one-time, daily, or weekly occurrence from decrypted config."""
        schedule = schedule_config.get("schedule", schedule_config) if isinstance(schedule_config, dict) else None
        if not isinstance(schedule, dict):
            raise ValueError("Decrypted workflow schedule must be an object")
        schedule_type = schedule.get("type")
        if schedule_type == "once":
            at_value = schedule.get("at")
            if not isinstance(at_value, str) or not at_value:
                raise ValueError("One-time workflow schedule requires at")
            try:
                candidate = datetime.fromisoformat(at_value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("One-time workflow schedule timestamp is invalid") from exc
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            return int(candidate.timestamp())
        time_value = schedule.get("time")
        if not isinstance(time_value, str):
            raise ValueError("Decrypted workflow schedule requires a time")
        try:
            hour, minute = (int(value) for value in time_value.split(":", 1))
        except ValueError as exc:
            raise ValueError("Decrypted workflow schedule time is invalid") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Decrypted workflow schedule time is invalid")
        try:
            schedule_timezone = ZoneInfo(str(schedule.get("timezone") or "UTC"))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Decrypted workflow schedule timezone is invalid") from exc

        current = datetime.fromtimestamp(now if now is not None else datetime.now(timezone.utc).timestamp(), timezone.utc)
        local_current = current.astimezone(schedule_timezone)
        if schedule_type == "daily":
            candidate = local_current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= local_current:
                candidate += timedelta(days=1)
            return int(candidate.timestamp())
        if schedule_type == "weekly":
            weekdays = schedule.get("weekdays")
            if not isinstance(weekdays, list):
                raise ValueError("Weekly workflow schedule requires weekdays")
            normalized_weekdays = {_weekday_index(day) for day in weekdays}
            if not normalized_weekdays:
                raise ValueError("Weekly workflow schedule requires weekdays")
            for offset in range(8):
                candidate = (local_current + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate.weekday() in normalized_weekdays and candidate > local_current:
                    return int(candidate.timestamp())
        raise ValueError("Workflow schedule type is not supported for unattended execution")

    @staticmethod
    def _required_string(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Workflow runtime claim returned invalid {field}")
        return value

    @staticmethod
    def _required_integer(payload: dict[str, Any], field: str) -> int:
        value = payload.get(field)
        if not isinstance(value, int) or value < 0:
            raise RuntimeError(f"Workflow runtime claim returned invalid {field}")
        return value


def _weekday_index(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError("Weekly workflow schedule weekday is invalid")
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    try:
        return weekdays[value.lower()]
    except KeyError as exc:
        raise ValueError("Weekly workflow schedule weekday is invalid") from exc
