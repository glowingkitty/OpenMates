"""Task app-skill assignment contract tests.

Tasks use the product-facing assignee names `user` and `openmates` while the
existing task storage model still uses `user` and `ai`. These helpers keep that
mapping explicit so the assistant cannot execute user-owned tasks by accident.
"""

from __future__ import annotations

import pytest

from backend.apps.tasks.skills.assignment import (
    TaskExecutionPermissionError,
    assert_openmates_task_for_execution,
    normalize_task_assignment,
)


def test_assignment_defaults_unclear_tasks_to_user() -> None:
    assignment = normalize_task_assignment(None)

    assert assignment.assignee == "user"
    assert assignment.storage_assignee_type == "user"


@pytest.mark.parametrize("raw", ["openmates", "OpenMates", "ai", "AI"])
def test_assignment_accepts_explicit_openmates_delegation(raw: str) -> None:
    assignment = normalize_task_assignment(raw)

    assert assignment.assignee == "openmates"
    assert assignment.storage_assignee_type == "ai"


@pytest.mark.parametrize("raw", ["", "alice", "me", "owner", "user"])
def test_assignment_treats_non_delegation_as_user(raw: str) -> None:
    assignment = normalize_task_assignment(raw)

    assert assignment.assignee == "user"
    assert assignment.storage_assignee_type == "user"


def test_assistant_execution_rejects_user_assigned_tasks() -> None:
    with pytest.raises(TaskExecutionPermissionError, match="assigned to user"):
        assert_openmates_task_for_execution({"task_id": "task-1", "assignee_type": "user"})


def test_assistant_execution_allows_openmates_assigned_tasks() -> None:
    assert_openmates_task_for_execution({"task_id": "task-1", "assignee_type": "ai"})
