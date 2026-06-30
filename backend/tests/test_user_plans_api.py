"""Tests for privacy-preserving user plan backend helpers.

Plans are durable coordination records for complex user/AI work. These tests
lock the Directus/service contract without a live CMS or FastAPI app.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods, hash_id
from backend.core.api.app.services.user_plan_service import UserPlanConflictError, UserPlanService


def plan_payload(**overrides):
    base = {
        "plan_id": "plan-1",
        "encrypted_plan_key": "cipher-plan-key",
        "encrypted_title": "cipher-title",
        "encrypted_goal": "cipher-goal",
        "encrypted_scope_in": "cipher-scope-in",
        "status": "draft",
        "primary_chat_id": "chat-1",
        "linked_project_ids": ["project-1"],
        "planner_focus_id": "openmates-plan",
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


def criterion_payload(**overrides):
    base = {
        "criterion_id": "AC-1",
        "encrypted_text": "cipher-ac",
        "type": "functional",
        "status": "pending",
        "required": True,
        "verification_ids": ["V-1"],
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


def verification_payload(**overrides):
    base = {
        "verification_id": "V-1",
        "kind": "automated_test",
        "phase": "green",
        "status": "pending",
        "required_for_done": True,
        "covers": ["AC-1"],
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_plan_hashes_owner_and_projects_without_plaintext_content() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1", **plan_payload()}))

    methods = UserPlanMethods(directus)
    created = await methods.create_plan("user-1", plan_payload())

    assert created is not None
    collection, record = directus.create_item.await_args.args
    assert collection == "user_plans"
    assert record["hashed_user_id"] == hash_id("user-1")
    assert record["hashed_primary_chat_id"] == hash_id("chat-1")
    assert record["linked_project_ids"] == [hash_id("project-1")]
    assert record["encrypted_title"] == "cipher-title"
    assert record["encrypted_plan_key"] == "cipher-plan-key"
    assert "title" not in record
    assert "goal" not in record


@pytest.mark.asyncio
async def test_update_rejects_stale_plan_version() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "version": 3, "plan_id": "plan-1"}])
    directus.update_item = AsyncMock()

    service = UserPlanService(UserPlanMethods(directus))

    with pytest.raises(UserPlanConflictError):
        await service.update_plan("plan-1", "user-1", {"status": "active", "version": 2})

    directus.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_blocks_missing_required_verification() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "row-1", "version": 1, **plan_payload(status="active")}],
        [criterion_payload(status="satisfied")],
        [verification_payload(status="pending")],
    ])
    directus.update_item = AsyncMock()

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.complete_plan("plan-1", "user-1", {"version": 1})

    assert result["plan"] is None
    assert result["blocked_by"] == [{"kind": "verification", "id": "V-1", "status": "pending"}]
    directus.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_red_phase_passed_unexpectedly_does_not_block_completion() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "row-1", "version": 1, **plan_payload(status="active")}],
        [criterion_payload(status="satisfied")],
        [verification_payload(phase="red", status="passed_unexpectedly", required_for_done=False)],
        [{"id": "row-1", "version": 1, **plan_payload(status="active")}],
    ])
    directus.update_item = AsyncMock(return_value={"id": "row-1", "status": "completed"})

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.complete_plan("plan-1", "user-1", {"version": 1, "updated_at": 200})

    assert result["blocked_by"] == []
    assert result["plan"]["status"] == "completed"


@pytest.mark.asyncio
async def test_create_verification_can_create_linked_verification_task() -> None:
    plan_methods = SimpleNamespace()
    plan_methods.get_plan = AsyncMock(return_value={"plan_id": "plan-1"})
    plan_methods.create_verification = AsyncMock(return_value={"plan_id": "plan-1", **verification_payload(linked_task_id="task-1")})
    task_service = SimpleNamespace(create_task=AsyncMock(return_value={"task_id": "task-1", "task_type": "verification"}))

    service = UserPlanService(plan_methods, task_service=task_service)
    result = await service.create_verification(
        "plan-1",
        "user-1",
        {
            **verification_payload(),
            "create_task": True,
            "task_id": "task-1",
            "encrypted_task_key": "cipher-task-key",
            "encrypted_title": "cipher-verification-task",
            "created_at": 100,
            "updated_at": 100,
        },
    )

    assert result["verification"]["linked_task_id"] == "task-1"
    task_service.create_task.assert_awaited_once()
    task_payload = task_service.create_task.await_args.args[1]
    assert task_payload["plan_id"] == "plan-1"
    assert task_payload["task_type"] == "verification"
    assert task_payload["verification_id"] == "V-1"
