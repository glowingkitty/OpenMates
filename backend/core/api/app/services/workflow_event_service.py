# backend/core/api/app/services/workflow_event_service.py
#
# Scoped workflow event matching for future chat, assistant action, app-skill,
# terminal, remote-dev, and sandbox triggers. This first slice is deterministic:
# no semantic matching runs unless a later AI classifier explicitly opts in.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowEventService:
    """Match workflow event trigger configs with scope filters and rate limits."""

    _last_match_by_key: dict[str, int] = field(default_factory=dict)

    def matches(self, trigger_config: dict[str, Any], event: dict[str, Any], now: int | None = None) -> bool:
        current_time = now if now is not None else int(time.time())
        if trigger_config.get("event_type") != event.get("type"):
            return False
        if not _scope_matches(trigger_config.get("scope") or {}, event.get("scope") or {}):
            return False
        if not _filters_match(trigger_config.get("filters") or [], event.get("payload") or {}):
            return False
        rate_limit_seconds = int(trigger_config.get("rate_limit_seconds") or 0)
        if rate_limit_seconds > 0:
            key = _rate_limit_key(trigger_config, event)
            last_match = self._last_match_by_key.get(key)
            if last_match is not None and current_time - last_match < rate_limit_seconds:
                return False
            self._last_match_by_key[key] = current_time
        return True


def _scope_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if value in (None, "", "*"):
            continue
        if actual.get(key) != value:
            return False
    return True


def _filters_match(filters: list[Any], payload: dict[str, Any]) -> bool:
    for item in filters:
        if not isinstance(item, dict):
            return False
        field = item.get("field")
        op = item.get("op")
        expected = item.get("value")
        actual = _value_at_path(payload, str(field or ""))
        if op == "contains":
            if expected not in str(actual or ""):
                return False
        elif op == "starts_with":
            if not str(actual or "").startswith(str(expected)):
                return False
        elif op == "eq":
            if actual != expected:
                return False
        elif op == "exists":
            if actual is None:
                return False
        else:
            return False
    return True


def _value_at_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not part:
            continue
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _rate_limit_key(trigger_config: dict[str, Any], event: dict[str, Any]) -> str:
    scope = event.get("scope") or {}
    return "|".join(
        [
            str(trigger_config.get("id") or trigger_config.get("event_type")),
            str(scope.get("user_id") or ""),
            str(scope.get("chat_id") or ""),
        ]
    )
