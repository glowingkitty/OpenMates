# contract-test-file: infrastructure
# backend/tests/test_app_skill_parallel_execution.py
# Verifies the metadata gate and bounded ordered executor for same-batch app skills.
# The tests use synthetic read-only operations so they do not call providers or mutate state.
# Stateful, task, system, and undeclared calls must stay on the serial execution path.

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from backend.tests.test_main_processor_invalid_tool_calls import main_processor
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition

# The existing fixture loads main_processor without optional worker dependencies.
MAX_PARALLEL_APP_SKILL_EXECUTIONS = main_processor.MAX_PARALLEL_APP_SKILL_EXECUTIONS
_execute_parallel_app_skill_operations = main_processor._execute_parallel_app_skill_operations
_create_parallel_app_skill_tasks = main_processor._create_parallel_app_skill_tasks
_cancel_parallel_app_skill_tasks = main_processor._cancel_parallel_app_skill_tasks
_is_parallel_safe_app_skill_batch = main_processor._is_parallel_safe_app_skill_batch


def _batch_metadata(*skills: AppSkillDefinition) -> dict[str, SimpleNamespace]:
    return {"web": SimpleNamespace(skills=list(skills))}


def _tool_call(name: str) -> SimpleNamespace:
    return SimpleNamespace(function_name=name)


def test_parallel_safe_defaults_to_false() -> None:
    skill = AppSkillDefinition(
        id="search",
        name_translation_key="search.name",
        description_translation_key="search.description",
    )

    assert skill.parallel_safe is False


def test_parallel_batch_requires_every_call_to_be_explicitly_safe() -> None:
    safe_skill = AppSkillDefinition(
        id="search",
        name_translation_key="search.name",
        description_translation_key="search.description",
        parallel_safe=True,
    )
    unsafe_skill = AppSkillDefinition(
        id="read",
        name_translation_key="read.name",
        description_translation_key="read.description",
    )
    resolver = {"web-search": ("web", "search"), "web-read": ("web", "read")}

    assert _is_parallel_safe_app_skill_batch(
        [_tool_call("web-search"), _tool_call("web-search")],
        resolver,
        _batch_metadata(safe_skill, unsafe_skill),
    )
    assert not _is_parallel_safe_app_skill_batch(
        [_tool_call("web-search"), _tool_call("web-read")],
        resolver,
        _batch_metadata(safe_skill, unsafe_skill),
    )


def test_parallel_batch_rejects_system_task_unknown_and_stateful_calls() -> None:
    safe_skill = AppSkillDefinition(
        id="search",
        name_translation_key="search.name",
        description_translation_key="search.description",
        parallel_safe=True,
    )
    metadata = _batch_metadata(safe_skill)
    resolver = {
        "web-search": ("web", "search"),
        "activate-focus-mode": ("system", "activate_focus_mode"),
        "task-create": ("task", "create"),
        "calendar-search": ("calendar", "search"),
    }

    for disallowed_name in ("activate-focus-mode", "task-create", "calendar-search", "unknown-tool"):
        assert not _is_parallel_safe_app_skill_batch(
            [_tool_call("web-search"), _tool_call(disallowed_name)],
            resolver,
            metadata,
        )


def test_parallel_batch_only_allows_audited_web_search() -> None:
    safe_skill = AppSkillDefinition(
        id="search",
        name_translation_key="calendar.search.name",
        description_translation_key="calendar.search.description",
        parallel_safe=True,
    )

    assert not _is_parallel_safe_app_skill_batch(
        [_tool_call("calendar-search"), _tool_call("calendar-search")],
        {"calendar-search": ("calendar", "search")},
        _batch_metadata(safe_skill),
    )


def test_parallel_executor_caps_concurrency_and_preserves_input_order() -> None:
    async def run() -> tuple[list[int], int]:
        active = 0
        peak_active = 0

        def operation(index: int):
            async def execute() -> int:
                nonlocal active, peak_active
                active += 1
                peak_active = max(peak_active, active)
                await asyncio.sleep(0.01 if index % 2 else 0)
                active -= 1
                return index

            return execute

        results = await _execute_parallel_app_skill_operations([operation(index) for index in range(7)])
        return results, peak_active

    results, peak_active = asyncio.run(run())

    assert results == list(range(7))
    assert peak_active == MAX_PARALLEL_APP_SKILL_EXECUTIONS


def test_live_dispatch_launcher_starts_concurrently_and_applies_results_in_input_order() -> None:
    async def run() -> tuple[list[str], list[str], int]:
        active = 0
        peak_active = 0
        started: list[str] = []

        def operation(name: str, delay: float):
            async def execute() -> str:
                nonlocal active, peak_active
                started.append(name)
                active += 1
                peak_active = max(peak_active, active)
                await asyncio.sleep(delay)
                active -= 1
                return name

            return execute

        names = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh"]
        tasks = _create_parallel_app_skill_tasks([
            operation(name, 0.02 if index % 2 == 0 else 0)
            for index, name in enumerate(names)
        ])
        await asyncio.sleep(0)
        applied = [await task for task in tasks]
        return started, applied, peak_active

    started, applied, peak_active = asyncio.run(run())

    assert started[:3] == ["first", "second", "third"]
    assert applied == ["first", "second", "third", "fourth", "fifth", "sixth", "seventh"]
    assert peak_active == MAX_PARALLEL_APP_SKILL_EXECUTIONS


def test_duplicate_and_budget_risk_batches_keep_the_live_dispatch_serial() -> None:
    source = inspect.getsource(main_processor.handle_main_processing)

    assert "parallel_tool_name not in allowed_tool_names" in source
    assert "learning_mode_active and is_learning_mode_blocked_skill" in source
    assert "if not isinstance(parallel_placeholder, dict)" in source
    assert "parallel_call_hash in parallel_hashes" in source
    assert "total_skill_calls + parallel_request_count > HARD_LIMIT_SKILL_CALLS" in source
    assert "or request_data.orchestration_id" in source
    assert "parallel_executions: Dict[str, Dict[str, Any]] = {}" in source
    assert 'parallel_outcome = parallel_execution["outcome"]' in source


def test_parallel_cancellation_drains_all_provider_tasks() -> None:
    async def run() -> list[bool]:
        started = asyncio.Event()

        async def operation() -> None:
            started.set()
            await asyncio.Event().wait()

        tasks = _create_parallel_app_skill_tasks([operation, operation, operation])
        await started.wait()
        executions = {
            str(index): {"task": task}
            for index, task in enumerate(tasks)
        }
        await _cancel_parallel_app_skill_tasks(executions)
        return [task.cancelled() for task in tasks]

    assert asyncio.run(run()) == [True, True, True]
