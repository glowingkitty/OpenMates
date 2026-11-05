"""Stateless locale-explicit sorting through the shared Rust SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from typing import Any, TypeVar, TypedDict

from .session_client import SessionClientError, _failure


class TaskOrderRow(TypedDict, total=False):
    position: int | float | None
    title: str | None
    source: str | None


_Row = TypeVar("_Row", bound=Mapping[str, Any])


def sort_tasks(tasks: Sequence[_Row], *, locale: str) -> list[_Row]:
    """Return a new list containing the original objects in shared SDK order."""
    if not isinstance(tasks, (list, tuple)) or not isinstance(locale, str):
        raise SessionClientError(
            "invalid_argument", "Supply task rows and an explicit locale."
        )
    try:
        rows = []
        for row in tasks:
            if not isinstance(row, Mapping):
                raise SessionClientError(
                    "invalid_argument", "Task ordering rows must be objects."
                )
            projected = {}
            for field in ("position", "title", "source"):
                if field not in row:
                    continue
                value = row[field]
                valid = value is None
                if (
                    field == "position"
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ):
                    try:
                        valid = math.isfinite(value)
                    except OverflowError:
                        valid = False
                elif field != "position" and isinstance(value, str):
                    valid = True
                if not valid:
                    raise SessionClientError(
                        "invalid_argument", "Invalid typed task ordering input."
                    )
                projected[field] = value
            rows.append(projected)
    except SessionClientError:
        raise
    except Exception:
        raise SessionClientError(
            "invalid_argument", "Invalid typed task ordering input."
        ) from None
    try:
        from ._native import task_order
    except ImportError:
        raise SessionClientError(
            "native_binding_unavailable",
            "Install a native SDK build containing task ordering.",
        ) from None
    try:
        encoded = json.dumps(
            {"locale": locale, "tasks": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded.encode("utf-8")
    except (ValueError, TypeError, OverflowError, UnicodeError):
        raise SessionClientError(
            "invalid_argument", "Invalid typed task ordering input."
        ) from None
    try:
        result = json.loads(task_order(encoded))
        indices = result.get("indices") if isinstance(result, dict) else None
        if (
            not isinstance(indices, list)
            or len(indices) != len(tasks)
            or any(
                type(index) is not int or index < 0 or index >= len(tasks)
                for index in indices
            )
            or len(set(indices)) != len(tasks)
        ):
            raise SessionClientError("protocol", "The native task order is invalid.")
        return [tasks[index] for index in indices]
    except Exception as error:
        raise _failure(error) from None
