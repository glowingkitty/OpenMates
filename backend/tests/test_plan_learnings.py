"""Tests for Plans V1 execution learnings.

Plan learnings are encrypted child records used to capture bounded workflow or
project-agent-instruction improvements before completion. These tests lock the
backend contract without a live Directus instance.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.user_plan_service import UserPlanService


def learning_payload(**overrides):
    base = {
        "learning_id": "LRN-1",
        "type": "workflow_improvement",
        "target_kind": "workflow",
        "status": "accepted",
        "severity": "medium",
        "confidence": "high",
        "linked_task_ids": ["task-1"],
        "linked_check_ids": ["V-1"],
        "encrypted_title": "cipher-title",
        "encrypted_observation": "cipher-observation",
        "encrypted_root_cause": "cipher-root-cause",
        "encrypted_suggested_change": "cipher-change",
        "encrypted_evidence_summary": "cipher-evidence",
        "encrypted_task_draft": "cipher-task-draft",
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_finalized_learning_count_blocks_completion_when_missing_or_excessive() -> None:
    plan_methods = SimpleNamespace(
        list_criteria=AsyncMock(return_value=[]),
        list_verifications=AsyncMock(return_value=[]),
        list_assumptions=AsyncMock(return_value=[]),
        list_reference_patterns=AsyncMock(return_value=[]),
        list_learnings=AsyncMock(return_value=[
            {"learning_id": "draft", "status": "draft"},
            {"learning_id": "rejected", "status": "rejected"},
            {"learning_id": "duplicate", "status": "duplicate"},
            {"learning_id": "merged", "status": "merged"},
        ]),
    )

    blockers = await UserPlanService(plan_methods).completion_blockers("plan-1")

    assert blockers == [{"kind": "missing_learnings", "status": "missing", "count": 0}]

    plan_methods.list_learnings.return_value = [
        {"learning_id": f"LRN-{index}", "status": "accepted"}
        for index in range(6)
    ]

    blockers = await UserPlanService(plan_methods).completion_blockers("plan-1")

    assert blockers == [{"kind": "excess_learnings", "status": "too_many", "count": 6}]


@pytest.mark.asyncio
async def test_learning_records_store_encrypted_content_and_safe_metadata() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "learning-row", **learning_payload()}))

    created = await UserPlanMethods(directus).create_learning("plan-1", learning_payload())

    assert created["learning_id"] == "LRN-1"
    collection, record = directus.create_item.await_args.args
    assert collection == "user_plan_learnings"
    assert record["plan_id"] == "plan-1"
    assert record["type"] == "workflow_improvement"
    assert record["target_kind"] == "workflow"
    assert record["status"] == "accepted"
    assert record["encrypted_title"] == "cipher-title"
    assert record["encrypted_task_draft"] == "cipher-task-draft"
    assert "title" not in record
    assert "observation" not in record
    assert "suggested_change" not in record


@pytest.mark.asyncio
async def test_invalid_learning_type_is_rejected_before_storage() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock()

    created = await UserPlanMethods(directus).create_learning("plan-1", learning_payload(type="global_instruction_mutation"))

    assert created is None
    directus.create_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_tasks_from_learnings_materializes_provenance_and_is_idempotent() -> None:
    learning = {"id": "learning-row", **learning_payload(status="accepted")}
    plan_methods = SimpleNamespace(
        get_plan=AsyncMock(return_value={"plan_id": "plan-1", "primary_chat_id": "chat-1", "encrypted_plan_key": "cipher-plan-key", "key_wrappers": [{"key_type": "master", "encrypted_plan_key": "cipher-plan-key"}]}),
        list_learnings=AsyncMock(return_value=[
            learning,
            {"id": "applied-row", **learning_payload(learning_id="LRN-2", status="applied", applied_task_id="task-existing")},
        ]),
        update_learning=AsyncMock(return_value={**learning, "status": "applied", "applied_task_id": "task-created"}),
    )
    task_service = SimpleNamespace(create_task=AsyncMock(return_value={"task_id": "task-created", "status": "backlog"}))

    result = await UserPlanService(plan_methods, task_service=task_service).create_tasks_from_learnings(
        "plan-1",
        "user-1",
        {"all": True, "created_at": 200, "updated_at": 200},
    )

    assert result["tasks"] == [{"task_id": "task-created", "status": "backlog"}]
    assert result["skipped"] == [{"learning_id": "LRN-2", "reason": "already_applied", "task_id": "task-existing"}]
    task_payload = task_service.create_task.await_args.args[1]
    assert task_payload["plan_id"] == "plan-1"
    assert task_payload["source_plan_id"] == "plan-1"
    assert task_payload["source_learning_id"] == "LRN-1"
    assert task_payload["status"] == "backlog"
    assert task_payload["task_type"] == "work"
    assert task_payload["encrypted_task_key"] == "cipher-plan-key"
    assert task_payload["key_wrappers"] == [{"key_type": "master", "encrypted_task_key": "cipher-plan-key"}]
    assert task_payload["encrypted_title"] == "cipher-title"
    assert task_payload["encrypted_description"] == "cipher-task-draft"
    plan_methods.update_learning.assert_awaited_once()
    update_patch = plan_methods.update_learning.await_args.args[2]
    assert update_patch["status"] == "applied"
    assert update_patch["applied_task_id"] == "task-created"


@pytest.mark.asyncio
async def test_create_tasks_from_learnings_requires_selected_records() -> None:
    plan_methods = SimpleNamespace(
        get_plan=AsyncMock(return_value={"plan_id": "plan-1"}),
        list_learnings=AsyncMock(return_value=[]),
    )

    with pytest.raises(ValueError, match="Select at least one learning"):
        await UserPlanService(plan_methods, task_service=SimpleNamespace()).create_tasks_from_learnings(
            "plan-1",
            "user-1",
            {},
        )


@pytest.mark.asyncio
async def test_active_context_guides_assistant_learning_completion_summary() -> None:
    plan_methods = SimpleNamespace(
        get_active_execution_context=AsyncMock(return_value={"plan_id": "plan-1", "primary_chat_id": "chat-1"}),
        list_criteria=AsyncMock(return_value=[]),
        list_verifications=AsyncMock(return_value=[]),
        list_assumptions=AsyncMock(return_value=[]),
        list_reference_patterns=AsyncMock(return_value=[]),
        list_learnings=AsyncMock(return_value=[]),
    )

    result = await UserPlanService(plan_methods).active_context("user-1", "chat-1", 200)

    assert result["blockers"] == [{"kind": "missing_learnings", "status": "missing", "count": 0}]
    assert result["completion_guidance"] == {
        "can_complete": False,
        "requires_learning_records": True,
        "final_response_sections": [],
    }

    plan_methods.list_learnings.return_value = [learning_payload(status="accepted")]
    result = await UserPlanService(plan_methods).active_context("user-1", "chat-1", 200)

    assert result["blockers"] == []
    assert result["completion_guidance"] == {
        "can_complete": True,
        "requires_learning_records": False,
        "final_response_sections": ["Learnings / Suggested Improvements"],
    }
