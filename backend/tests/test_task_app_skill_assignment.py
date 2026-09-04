"""Task app-skill assignment Specification tests.

Tasks use the persisted assignee names `user` and `openmates`. These helpers
keep native execution ownership explicit so the assistant cannot execute
user-owned or external-AI Tasks by accident.
"""

from __future__ import annotations

import pytest

from backend.apps.tasks.skills.assignment import (
    TaskExecutionPermissionError,
    assert_openmates_task_for_execution,
    normalize_task_assignment,
)


# contract-test: direct surface=rest_api assertions=tasks.assignment.identity-separated,tasks.execution.capacity-scoped
def test_assignment_defaults_unclear_tasks_to_user() -> None:
    assignment = normalize_task_assignment(None)

    assert assignment.assignee == "user"
    assert assignment.storage_assignee_type == "user"


# contract-test: direct surface=rest_api assertions=tasks.assignment.identity-separated,tasks.execution.capacity-scoped
@pytest.mark.parametrize("raw", ["openmates", "OpenMates"])
def test_assignment_accepts_explicit_openmates_delegation(raw: str) -> None:
    assignment = normalize_task_assignment(raw)

    assert assignment.assignee == "openmates"
    assert assignment.storage_assignee_type == "openmates"


# contract-test: supporting surface=rest_api assertions=tasks.assignment.identity-separated
@pytest.mark.parametrize("raw", ["", "alice", "me", "owner", "user"])
def test_assignment_treats_non_delegation_as_user(raw: str) -> None:
    assignment = normalize_task_assignment(raw)

    assert assignment.assignee == "user"
    assert assignment.storage_assignee_type == "user"


# contract-test: direct surface=rest_api assertions=tasks.assignment.identity-separated
@pytest.mark.parametrize("raw", ["ai", "AI"])
def test_assignment_does_not_accept_removed_ai_alias(raw: str) -> None:
    assert normalize_task_assignment(raw).storage_assignee_type == "user"


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
def test_assistant_execution_rejects_user_assigned_tasks() -> None:
    with pytest.raises(TaskExecutionPermissionError, match="assigned to user"):
        assert_openmates_task_for_execution({"task_id": "task-1", "assignee_type": "user"})


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
def test_assistant_execution_allows_openmates_assigned_tasks() -> None:
    assert_openmates_task_for_execution({"task_id": "task-1", "assignee_type": "openmates", "assignee_identity": "openmates"})
