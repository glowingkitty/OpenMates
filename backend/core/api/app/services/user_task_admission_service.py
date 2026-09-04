# backend/core/api/app/services/user_task_admission_service.py
#
# Central admission policy for user-facing AI Tasks. Capacity is scoped to a
# personal account or Team, while chat and Plan lanes determine which Tasks are
# eligible before priority is considered. Workflow runs are intentionally absent
# because their runtime owns separate execution and concurrency semantics.

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from backend.core.api.app.utils.server_mode import resolve_runtime_deployment_mode

OFFICIAL_PERSONAL_NORMAL_CAPACITY = 5
OFFICIAL_PERSONAL_URGENT_RESERVE = 2
OFFICIAL_TEAM_NORMAL_CAPACITY = 8
OFFICIAL_TEAM_URGENT_RESERVE = 2
URGENT_PRIORITY = 4
ADMISSION_QUERY_LIMIT = 500
TASK_QUEUE_STAGING_STATE = "staging"

PERSONAL_NORMAL_ENV = "OPENMATES_PERSONAL_TASK_CONCURRENCY"
PERSONAL_URGENT_ENV = "OPENMATES_PERSONAL_TASK_URGENT_RESERVE"
TEAM_NORMAL_ENV = "OPENMATES_TEAM_TASK_CONCURRENCY"
TEAM_URGENT_ENV = "OPENMATES_TEAM_TASK_URGENT_RESERVE"


@dataclass(frozen=True)
class TaskCapacity:
    normal: int
    urgent_reserve: int

    @property
    def hard_maximum(self) -> int:
        return self.normal + self.urgent_reserve


@dataclass(frozen=True)
class TaskAdmissionPolicy:
    personal: TaskCapacity
    team: TaskCapacity


def _configured_int(values: Mapping[str, str], name: str, default: int, *, allow_zero: bool = False) -> int:
    raw = values.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def load_task_admission_policy(
    *,
    env: Mapping[str, str] | None = None,
    official_cloud: bool | None = None,
) -> TaskAdmissionPolicy:
    values = os.environ if env is None else env
    if official_cloud is None:
        mode = resolve_runtime_deployment_mode(env=values)
        official_cloud = mode.effective_mode == "official_cloud" and mode.status == "valid"
    if official_cloud:
        return TaskAdmissionPolicy(
            personal=TaskCapacity(OFFICIAL_PERSONAL_NORMAL_CAPACITY, OFFICIAL_PERSONAL_URGENT_RESERVE),
            team=TaskCapacity(OFFICIAL_TEAM_NORMAL_CAPACITY, OFFICIAL_TEAM_URGENT_RESERVE),
        )
    return TaskAdmissionPolicy(
        personal=TaskCapacity(
            _configured_int(values, PERSONAL_NORMAL_ENV, OFFICIAL_PERSONAL_NORMAL_CAPACITY),
            _configured_int(values, PERSONAL_URGENT_ENV, OFFICIAL_PERSONAL_URGENT_RESERVE, allow_zero=True),
        ),
        team=TaskCapacity(
            _configured_int(values, TEAM_NORMAL_ENV, OFFICIAL_TEAM_NORMAL_CAPACITY),
            _configured_int(values, TEAM_URGENT_ENV, OFFICIAL_TEAM_URGENT_RESERVE, allow_zero=True),
        ),
    )


class TaskAdmissionService:
    def __init__(
        self,
        task_methods: Any,
        *,
        policy: TaskAdmissionPolicy | None = None,
        on_admitted: Callable[[dict[str, Any], int], Awaitable[bool]] | None = None,
    ):
        self.task_methods = task_methods
        self.policy = policy or load_task_admission_policy()
        self.on_admitted = on_admitted

    async def admit_available(
        self,
        user_id: str,
        *,
        team_id: str | None = None,
        now: int | None = None,
        preferred_chat_id: str | None = None,
    ) -> dict[str, Any]:
        current_time = int(now or time.time())
        scope = "team" if team_id else "personal"
        scope_id = team_id or user_id
        return await self._admit_with_refill(
            user_id=user_id,
            team_id=team_id,
            scope=scope,
            scope_id=scope_id,
            current_time=current_time,
            preferred_chat_id=preferred_chat_id,
        )

    async def admit_hashed_scope(self, scope: str, owner_hash: str, *, now: int | None = None) -> dict[str, Any]:
        if scope not in {"personal", "team"}:
            raise ValueError("Task admission scope must be personal or team")
        return await self._admit_with_refill(
            user_id="",
            team_id=None,
            scope=scope,
            scope_id=owner_hash,
            current_time=int(now or time.time()),
            preferred_chat_id=None,
            owner_hash=owner_hash,
        )

    async def _admit_with_refill(self, **scope_args: Any) -> dict[str, Any]:
        admitted_tasks: list[dict[str, Any]] = []
        waiting_task_ids: set[str] = set()
        failed_task_ids: set[str] = set()
        while True:
            result = await self._admit_scope(**scope_args, excluded_task_ids=failed_task_ids)
            admitted_tasks.extend(result["admitted_tasks"])
            waiting_task_ids.update(result["waiting_task_ids"])
            failed_task_ids.update(result["failed_task_ids"])
            if result["dispatch_failures"] == 0:
                return {
                    "scope": result["scope"],
                    "active": result["active"],
                    "admitted_task_ids": [str(task.get("task_id") or "") for task in admitted_tasks],
                    "admitted_tasks": admitted_tasks,
                    "waiting_task_ids": sorted(waiting_task_ids),
                }

    async def _admit_scope(
        self,
        *,
        user_id: str,
        team_id: str | None,
        scope: str,
        scope_id: str,
        current_time: int,
        preferred_chat_id: str | None,
        owner_hash: str | None = None,
        excluded_task_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        capacity = self.policy.team if team_id else self.policy.personal
        if scope == "team":
            capacity = self.policy.team
        lock_token = (
            await self.task_methods.acquire_hashed_admission_lock(scope, scope_id)
            if owner_hash
            else await self.task_methods.acquire_admission_lock(scope, scope_id)
        )
        claimed_tasks: list[dict[str, Any]] = []
        try:
            tasks = (
                await self.task_methods.list_open_tasks_for_hashed_admission(scope, owner_hash, limit=ADMISSION_QUERY_LIMIT)
                if owner_hash
                else await self.task_methods.list_open_tasks_for_admission(user_id, team_id=team_id, limit=ADMISSION_QUERY_LIMIT)
            )
            active = [task for task in tasks if self._is_active_ai_task(task)]
            candidates, wait_states = await self._eligible_lane_heads(
                tasks,
                now=current_time,
            )
            unblocked_candidates: list[dict[str, Any]] = []
            for task in candidates:
                task_id = str(task.get("task_id") or "")
                if scope == "personal" and await self.task_methods.admission_blockers(task, user_id, owner_hash=owner_hash):
                    wait_states[task_id] = "waiting_for_plan_dependency"
                    continue
                unblocked_candidates.append(task)
            candidates = unblocked_candidates
            candidates = [task for task in candidates if str(task.get("task_id") or "") not in (excluded_task_ids or set())]
            candidates.sort(key=lambda task: self._candidate_sort_key(task, preferred_chat_id=preferred_chat_id))

            active_total = len(active)
            active_normal = sum(not self._is_urgent(task) for task in active)
            waiting_task_ids: list[str] = []
            for task in candidates:
                urgent = self._is_urgent(task)
                has_slot = active_total < capacity.hard_maximum and (urgent or active_normal < capacity.normal)
                task_id = str(task.get("task_id") or "")
                if not has_slot:
                    wait_states[task_id] = "waiting_for_capacity"
                    continue
                claimed = await self.task_methods.claim_ai_task(task, current_time)
                if not claimed:
                    continue
                claimed_tasks.append(claimed)
                active_total += 1
                if not urgent:
                    active_normal += 1

            for task in tasks:
                task_id = str(task.get("task_id") or "")
                state = wait_states.get(task_id)
                if not state or any(str(claimed.get("task_id") or "") == task_id for claimed in claimed_tasks) or not self._is_waiting_ai_task(task):
                    continue
                waiting_task_ids.append(task_id)
                if task.get("ai_execution_state") != state:
                    await self.task_methods.set_ai_task_waiting(task, state, current_time)

        finally:
            if owner_hash:
                await self.task_methods.release_hashed_admission_lock(scope, scope_id, lock_token)
            else:
                await self.task_methods.release_admission_lock(scope, scope_id, lock_token)

        admitted_tasks: list[dict[str, Any]] = []
        dispatch_failures = 0
        failed_task_ids: list[str] = []
        for claimed in claimed_tasks:
            if self.on_admitted and not await self.on_admitted(claimed, current_time):
                active_total -= 1
                dispatch_failures += 1
                failed_task_ids.append(str(claimed.get("task_id") or ""))
                continue
            admitted_tasks.append(claimed)
        return {
            "scope": scope,
            "active": active_total,
            "admitted_task_ids": [str(task.get("task_id") or "") for task in admitted_tasks],
            "admitted_tasks": admitted_tasks,
            "waiting_task_ids": waiting_task_ids,
            "dispatch_failures": dispatch_failures,
            "failed_task_ids": failed_task_ids,
        }

    async def _eligible_lane_heads(
        self,
        tasks: list[dict[str, Any]],
        *,
        now: int,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        candidates: list[dict[str, Any]] = []
        wait_states: dict[str, str] = {}
        active_chat_ids = {
            str(task.get("primary_chat_id"))
            for task in tasks
            if task.get("primary_chat_id") and self._is_active_ai_task(task)
        }

        plan_tasks: dict[str, list[dict[str, Any]]] = {}
        chat_tasks: dict[str, list[dict[str, Any]]] = {}
        standalone_tasks: list[dict[str, Any]] = []
        for task in tasks:
            plan_id = str(task.get("plan_id") or "")
            chat_id = str(task.get("primary_chat_id") or "")
            if plan_id:
                plan_tasks.setdefault(plan_id, []).append(task)
            elif chat_id:
                chat_tasks.setdefault(chat_id, []).append(task)
            else:
                standalone_tasks.append(task)

        plan_chat_ids: set[str] = set()
        for lane_tasks in plan_tasks.values():
            ordered = sorted(lane_tasks, key=self._lane_sort_key)
            active_plan_task = next((task for task in ordered if self._is_active_ai_task(task)), None)
            if active_plan_task is not None:
                chat_id = str(active_plan_task.get("primary_chat_id") or "")
                if chat_id:
                    plan_chat_ids.add(chat_id)
                for task in ordered:
                    if self._is_waiting_ai_task(task):
                        wait_states[str(task.get("task_id") or "")] = "waiting_for_plan_dependency"
                continue
            current = ordered[0] if ordered else None
            for task in ordered[1:]:
                if self._is_waiting_ai_task(task):
                    wait_states[str(task.get("task_id") or "")] = "waiting_for_plan_dependency"
            if current is None:
                continue
            chat_id = str(current.get("primary_chat_id") or "")
            if chat_id:
                plan_chat_ids.add(chat_id)
            if chat_id in active_chat_ids or not self._can_start(current, now):
                continue
            candidates.append(current)

        for chat_id, lane_tasks in chat_tasks.items():
            ordered = sorted(lane_tasks, key=self._lane_sort_key)
            if chat_id in active_chat_ids or chat_id in plan_chat_ids:
                for task in ordered:
                    if self._is_waiting_ai_task(task):
                        wait_states[str(task.get("task_id") or "")] = "waiting_for_previous_task"
                continue
            head = ordered[0] if ordered else None
            for task in ordered[1:]:
                if self._is_waiting_ai_task(task):
                    wait_states[str(task.get("task_id") or "")] = "waiting_for_previous_task"
            if head and self._can_start(head, now):
                candidates.append(head)

        for task in standalone_tasks:
            if self._can_start(task, now):
                candidates.append(task)

        return candidates, wait_states

    def _can_start(self, task: dict[str, Any], now: int) -> bool:
        if not self._is_waiting_ai_task(task):
            return False
        due_at = task.get("due_at")
        return due_at is None or int(due_at) <= now

    def _is_active_ai_task(self, task: dict[str, Any]) -> bool:
        return task.get("assignee_type") == "ai" and task.get("status") == "in_progress"

    def _is_waiting_ai_task(self, task: dict[str, Any]) -> bool:
        return (
            task.get("assignee_type") == "ai"
            and task.get("status") == "todo"
            and task.get("queue_state") != "skipped"
            and task.get("queue_state") != TASK_QUEUE_STAGING_STATE
        )

    def _is_urgent(self, task: dict[str, Any]) -> bool:
        return self._sort_int(task.get("priority")) == URGENT_PRIORITY

    def _lane_sort_key(self, task: dict[str, Any]) -> tuple[int, int, str]:
        return (
            self._sort_int(task.get("position")),
            self._sort_int(task.get("created_at")),
            str(task.get("task_id") or ""),
        )

    def _candidate_sort_key(self, task: dict[str, Any], *, preferred_chat_id: str | None) -> tuple[int, int, int, int, str]:
        return (
            0 if self._is_urgent(task) else 1,
            0 if preferred_chat_id and task.get("primary_chat_id") == preferred_chat_id else 1,
            self._sort_int(task.get("due_at")),
            self._sort_int(task.get("position")),
            str(task.get("task_id") or ""),
        )

    def _sort_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
