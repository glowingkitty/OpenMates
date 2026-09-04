"""Contract tests for scoped user Task admission.

These tests keep personal and Team capacity independent from ordered execution
lanes. Workflow runs are deliberately absent because they are owned by the
Workflow runtime and never consume user Task admission slots.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.user_task_admission_service import (
    TaskAdmissionService,
    load_task_admission_policy,
)
from backend.core.api.app.services.directus.user_task_methods import hash_id
from backend.core.api.app.services.user_task_execution_service import UserTaskExecutionService


def _task(task_id: str, **overrides):
    task = {
        "id": f"row-{task_id}",
        "task_id": task_id,
        "status": "todo",
        "assignee_type": "openmates",
        "assignee_identity": "openmates",
        "priority": 0,
        "position": 0,
        "version": 1,
        "created_at": 100,
    }
    task.update(overrides)
    return task


def _service(tasks, *, policy=None, plans=None):
    methods = AsyncMock()
    methods.list_open_tasks_for_admission.return_value = tasks
    methods.admission_blockers.return_value = []
    methods.acquire_admission_lock.return_value = "lock-token"
    methods.claim_ai_task.side_effect = lambda task, now: {**task, "status": "in_progress", "ai_execution_state": "queued"}
    methods.set_ai_task_waiting.side_effect = lambda task, state, now: {**task, "ai_execution_state": state}
    plan_methods = AsyncMock()
    plan_methods.get_plan.side_effect = lambda plan_id, _user_id, _team_id=None: (plans or {}).get(plan_id)
    return TaskAdmissionService(methods, policy=policy), methods, plan_methods


# contract-test: direct surface=rest_api assertions=tasks.assignment.identity-separated,tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_external_ai_tasks_never_enter_native_openmates_admission() -> None:
    service, methods, _plans = _service([
        _task("opencode", assignee_type="external_ai", assignee_identity="opencode"),
    ])

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == []
    methods.claim_ai_task.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
def test_official_cloud_policy_uses_fixed_personal_and_team_limits() -> None:
    policy = load_task_admission_policy(
        env={
            "OPENMATES_PERSONAL_TASK_CONCURRENCY": "99",
            "OPENMATES_PERSONAL_TASK_URGENT_RESERVE": "99",
            "OPENMATES_TEAM_TASK_CONCURRENCY": "99",
            "OPENMATES_TEAM_TASK_URGENT_RESERVE": "99",
        },
        official_cloud=True,
    )

    assert (policy.personal.normal, policy.personal.urgent_reserve, policy.personal.hard_maximum) == (5, 2, 7)
    assert (policy.team.normal, policy.team.urgent_reserve, policy.team.hard_maximum) == (8, 2, 10)


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
def test_self_host_policy_accepts_explicit_capacity_and_rejects_invalid_values() -> None:
    policy = load_task_admission_policy(
        env={
            "OPENMATES_PERSONAL_TASK_CONCURRENCY": "3",
            "OPENMATES_PERSONAL_TASK_URGENT_RESERVE": "1",
            "OPENMATES_TEAM_TASK_CONCURRENCY": "12",
            "OPENMATES_TEAM_TASK_URGENT_RESERVE": "3",
        },
        official_cloud=False,
    )

    assert policy.personal.hard_maximum == 4
    assert policy.team.hard_maximum == 15

    with pytest.raises(ValueError, match="OPENMATES_PERSONAL_TASK_CONCURRENCY"):
        load_task_admission_policy(env={"OPENMATES_PERSONAL_TASK_CONCURRENCY": "0"}, official_cloud=False)


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_personal_pool_starts_two_urgent_overflow_tasks_but_not_sixth_normal() -> None:
    active = [_task(f"active-{index}", status="in_progress", priority=0) for index in range(5)]
    waiting = [
        _task("normal-waiting", priority=0),
        _task("urgent-1", priority=4),
        _task("urgent-2", priority=4),
    ]
    service, methods, _plans = _service(active + waiting)

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == ["urgent-1", "urgent-2"]
    assert result["waiting_task_ids"] == ["normal-waiting"]
    assert methods.claim_ai_task.await_count == 2
    methods.acquire_admission_lock.assert_awaited_once_with("personal", "user-1")


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_team_pool_has_hard_maximum_ten_and_is_independent_from_personal_pool() -> None:
    active = [_task(f"active-{index}", status="in_progress") for index in range(8)]
    waiting = [_task("urgent-1", priority=4), _task("urgent-2", priority=4), _task("urgent-3", priority=4)]
    service, methods, _plans = _service(active + waiting)

    result = await service.admit_available("actor-user", team_id="team-1", now=200)

    assert result["scope"] == "team"
    assert result["admitted_task_ids"] == ["urgent-1", "urgent-2"]
    assert result["waiting_task_ids"] == ["urgent-3"]
    methods.list_open_tasks_for_admission.assert_awaited_once_with("actor-user", team_id="team-1", limit=500)
    methods.acquire_admission_lock.assert_awaited_once_with("team", "team-1")


# contract-test: direct surface=rest_api assertions=tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_urgent_chat_task_cannot_skip_user_ordered_predecessor() -> None:
    tasks = [
        _task("first", primary_chat_id="chat-1", position=10),
        _task("urgent-later", primary_chat_id="chat-1", position=20, priority=4),
    ]
    service, methods, _plans = _service(tasks)

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == ["first"]
    assert methods.claim_ai_task.await_args.args[0]["task_id"] == "first"


# contract-test: direct surface=rest_api assertions=tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_user_reorder_changes_next_chat_task_without_preemption() -> None:
    tasks = [
        _task("previously-first", primary_chat_id="chat-1", position=20),
        _task("moved-first", primary_chat_id="chat-1", position=10),
    ]
    service, methods, _plans = _service(tasks)

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == ["moved-first"]
    assert methods.claim_ai_task.await_args.args[0]["task_id"] == "moved-first"


# contract-test: direct surface=rest_api assertions=tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_plan_lane_uses_first_open_task_without_plan_pointer_lookup() -> None:
    tasks = [
        _task("plan-first", plan_id="plan-1", position=10),
        _task("plan-later", plan_id="plan-1", position=20, priority=4),
    ]
    service, methods, plans = _service(tasks)

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == ["plan-first"]
    assert result["waiting_task_ids"] == ["plan-later"]
    assert methods.claim_ai_task.await_args.args[0]["task_id"] == "plan-first"
    plans.get_plan.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.dependencies.done-only,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_unsatisfied_dependency_blocks_automatic_admission() -> None:
    service, methods, _plans = _service([_task("blocked")])
    methods.admission_blockers.return_value = [{"ref": "task:prerequisite", "status": "todo"}]

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == []
    assert result["waiting_task_ids"] == ["blocked"]
    methods.claim_ai_task.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_active_plan_task_prevents_another_plan_task_after_reorder() -> None:
    tasks = [
        _task("reordered-todo", plan_id="plan-1", position=10),
        _task("active", plan_id="plan-1", position=20, status="in_progress"),
    ]
    service, methods, _plans = _service(tasks)

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == []
    assert result["waiting_task_ids"] == ["reordered-todo"]
    methods.claim_ai_task.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=plans.approval.human-web-revision-bound,plans.assumptions.investigated-before-work,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_plan_gate_blockers_prevent_automatic_admission() -> None:
    service, methods, _plans = _service([_task("blocked", plan_id="plan-1")])
    methods.admission_blockers.return_value = [{"kind": "approval", "id": "plan-1", "status": "unapproved"}]

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == []
    assert result["waiting_task_ids"] == ["blocked"]


# contract-test: direct surface=rest_api assertions=plans.dependencies.done-only,plans.approval.human-web-revision-bound,tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_hashed_scheduler_admission_uses_owner_hash_for_work_control_gates() -> None:
    service, methods, _plans = _service([])
    task = _task("scheduled", hashed_user_id="owner-hash")
    methods.list_open_tasks_for_hashed_admission.return_value = [task]
    methods.admission_blockers.return_value = [{"ref": "task:prerequisite", "status": "todo"}]
    methods.acquire_hashed_admission_lock.return_value = "lock-token"

    result = await service.admit_hashed_scope("personal", "owner-hash", now=200)

    assert result["admitted_task_ids"] == []
    methods.admission_blockers.assert_awaited_once_with(task, "", owner_hash="owner-hash")


# contract-test: direct surface=rest_api assertions=tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_active_task_prevents_second_task_in_same_chat() -> None:
    tasks = [
        _task("active-plan-task", status="in_progress", plan_id="plan-1", primary_chat_id="chat-1"),
        _task("ordinary-chat-task", primary_chat_id="chat-1"),
    ]
    service, methods, _plans = _service(tasks)

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == []
    assert result["waiting_task_ids"] == ["ordinary-chat-task"]
    methods.claim_ai_task.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.workflow-projections.read-only
@pytest.mark.asyncio
async def test_admission_reads_only_user_task_rows_not_workflow_projections() -> None:
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[]))
    from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods

    await UserTaskMethods(directus).list_open_tasks_for_admission("user-1")

    collection = directus.get_items.await_args.args[0]
    assert collection == "user_tasks"
    assert "workflow" not in collection


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_admission_queries_are_bounded_and_paginated_without_truncation() -> None:
    pages = [
        [{"task_id": "task-1"}, {"task_id": "task-2"}],
        [{"task_id": "task-3"}],
    ]
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=pages))
    from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods

    rows = await UserTaskMethods(directus).list_open_tasks_for_admission("user-1", limit=2)

    assert [row["task_id"] for row in rows] == ["task-1", "task-2", "task-3"]
    assert [call.kwargs["params"]["limit"] for call in directus.get_items.await_args_list] == [2, 2]
    assert "filter[task_id][_gt]" not in directus.get_items.await_args_list[0].kwargs["params"]
    assert directus.get_items.await_args_list[1].kwargs["params"]["filter[task_id][_gt]"] == "task-2"


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_team_admission_finds_staged_context_without_personal_owner_hash() -> None:
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[{"id": "context-1"}]))
    from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods

    context = await UserTaskMethods(directus).get_task_execution_context_for_admission(
        {
            "task_id": "team-task",
            "primary_chat_id": "team-chat",
            "hashed_user_id": None,
            "hashed_team_id": hash_id("team-1"),
        },
        now=200,
    )

    assert context == {"id": "context-1"}
    params = directus.get_items.await_args.kwargs["params"]
    assert "filter[hashed_user_id][_eq]" not in params
    assert params["filter[hashed_task_id][_eq]"] == hash_id("team-task")


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_waiting_task_execution_context_is_vault_encrypted_and_dispatched_once_admitted() -> None:
    methods = AsyncMock()
    encryption = AsyncMock()
    encryption.encrypt.return_value = ("vault:v1:ciphertext", "v1")
    encryption.decrypt.return_value = '{"task_id":"task-1","user_id":"user-1","chat_id":"chat-1","instruction":"Do the task","created_at":100}'
    methods.create_task_execution_context.return_value = {"id": "context-1"}
    methods.get_task_execution_context_for_admission.return_value = {"encrypted_context": "vault:v1:ciphertext"}
    dispatcher = AsyncMock(return_value={"task_id": "ai-run-1"})
    cache = AsyncMock()
    execution = UserTaskExecutionService(
        methods,
        encryption_service=encryption,
        cache_service=cache,
        ai_dispatcher=dispatcher,
    )

    await execution.stage(
        task_id="task-1",
        user_id="user-1",
        chat_id="chat-1",
        instruction="Do the task",
        current_chat_title=None,
        created_at=100,
    )
    dispatched = await execution.dispatch_admitted(
        _task("task-1", primary_chat_id="chat-1", hashed_user_id=hash_id("user-1")),
        200,
    )

    assert dispatched is True
    methods.create_task_execution_context.assert_awaited_once()
    dispatcher.assert_awaited_once()
    assert dispatcher.await_args.args[:2] == ("ai", "ask")
    assert dispatcher.await_args.args[2]["user_task_id"] == "task-1"
    cache.set_active_ai_task.assert_awaited_once_with("chat-1", "ai-run-1")


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_scheduler_admission_blocks_claim_without_execution_context_and_releases_slot() -> None:
    waiting = _task("task-1", primary_chat_id="chat-1", hashed_user_id=hash_id("user-1"))
    claimed = {**waiting, "status": "in_progress", "version": 2}
    service, methods, _plans = _service([waiting])
    methods.claim_ai_task.side_effect = None
    methods.claim_ai_task.return_value = claimed
    methods.get_task_execution_context_for_admission.return_value = None
    execution = UserTaskExecutionService(methods, encryption_service=AsyncMock())
    service.on_admitted = execution.dispatch_admitted

    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == []
    methods.fail_claimed_ai_task.assert_awaited_once_with(claimed, "missing_execution_context", 200)


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_scheduler_dispatch_failure_blocks_claim_and_releases_slot() -> None:
    task = _task("task-1", primary_chat_id="chat-1", hashed_user_id=hash_id("user-1"), version=2)
    methods = AsyncMock()
    methods.get_task_execution_context_for_admission.return_value = {"encrypted_context": "vault:v1:ciphertext"}
    encryption = AsyncMock()
    encryption.decrypt.return_value = '{"task_id":"task-1","user_id":"user-1","chat_id":"chat-1","instruction":"Do it"}'
    dispatcher = AsyncMock(side_effect=RuntimeError("dispatch failed"))
    execution = UserTaskExecutionService(methods, encryption_service=encryption, ai_dispatcher=dispatcher)

    dispatched = await execution.dispatch_admitted(task, 200)

    assert dispatched is False
    methods.fail_claimed_ai_task.assert_awaited_once_with(task, "ai_dispatch_failed", 200)


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_execution_context_decrypt_failure_blocks_claim_and_releases_slot() -> None:
    task = _task("task-1", primary_chat_id="chat-1", hashed_user_id=hash_id("user-1"), version=2)
    methods = AsyncMock()
    methods.get_task_execution_context_for_admission.return_value = {"encrypted_context": "vault:v1:corrupt"}
    encryption = AsyncMock()
    encryption.decrypt.side_effect = RuntimeError("Vault unavailable")
    execution = UserTaskExecutionService(methods, encryption_service=encryption)

    dispatched = await execution.dispatch_admitted(task, 200)

    assert dispatched is False
    methods.fail_claimed_ai_task.assert_awaited_once_with(task, "invalid_execution_context", 200)


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_failed_dispatch_immediately_refills_released_capacity() -> None:
    first = _task("task-1", position=1)
    second = _task("task-2", position=2)
    policy = load_task_admission_policy(
        env={
            "OPENMATES_PERSONAL_TASK_CONCURRENCY": "1",
            "OPENMATES_PERSONAL_TASK_URGENT_RESERVE": "0",
            "OPENMATES_TEAM_TASK_CONCURRENCY": "1",
            "OPENMATES_TEAM_TASK_URGENT_RESERVE": "0",
        },
        official_cloud=False,
    )
    service, methods, _plans = _service([first, second], policy=policy)
    methods.list_open_tasks_for_admission.side_effect = [[first, second], [second]]
    dispatch_results = iter([False, True])

    async def on_admitted(_task_value: dict, _now: int) -> bool:
        return next(dispatch_results)

    service.on_admitted = on_admitted
    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == ["task-2"]
    assert methods.acquire_admission_lock.await_count == 2


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_admission_releases_scope_lock_before_dispatch_callback() -> None:
    waiting = _task("task-1", primary_chat_id="chat-1")
    service, methods, _plans = _service([waiting])
    events: list[str] = []
    methods.release_admission_lock.side_effect = lambda *_args: events.append("released")

    async def on_admitted(_task_value: dict, _now: int) -> bool:
        events.append("dispatched")
        return True

    service.on_admitted = on_admitted
    result = await service.admit_available("user-1", now=200)

    assert result["admitted_task_ids"] == ["task-1"]
    assert events == ["released", "dispatched"]
