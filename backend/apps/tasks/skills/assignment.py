# backend/apps/tasks/skills/assignment.py
#
# Assignment helpers for Tasks app skills. Product-facing embeds use `user` and
# `openmates`, matching durable assignment semantics. Named external agents are
# deliberately not executable by the native OpenMates task runtime.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProductAssignee = Literal["user", "openmates"]
StorageAssigneeType = Literal["user", "openmates"]

OPENMATES_ASSIGNEE_VALUES = {"openmates"}


class TaskExecutionPermissionError(ValueError):
    """Raised when the assistant tries to execute a user-assigned task."""


@dataclass(frozen=True, slots=True)
class TaskAssignment:
    assignee: ProductAssignee
    storage_assignee_type: StorageAssigneeType


def normalize_task_assignment(raw_assignee: Any) -> TaskAssignment:
    """Normalize product-facing task assignment, defaulting unclear values to user."""
    normalized = str(raw_assignee or "").strip().lower()
    if normalized in OPENMATES_ASSIGNEE_VALUES:
        return TaskAssignment(assignee="openmates", storage_assignee_type="openmates")
    return TaskAssignment(assignee="user", storage_assignee_type="user")


def product_assignee_from_storage(assignee_type: Any) -> ProductAssignee:
    return "openmates" if str(assignee_type or "").strip().lower() == "openmates" else "user"


def assert_openmates_task_for_execution(task: dict[str, Any]) -> None:
    """Allow assistant execution only for tasks explicitly assigned to OpenMates."""
    if product_assignee_from_storage(task.get("assignee_type")) != "openmates":
        task_id = task.get("short_id") or task.get("task_id") or "task"
        raise TaskExecutionPermissionError(f"{task_id} is assigned to user and cannot be executed by OpenMates")
