# contract-test-file: infrastructure
"""Inline sandbox file tools keep the turn's iteration budget, like device-path pauses do.

On the device path every Project file operation pauses the turn and its continuation
starts a fresh budget. Inline sandbox operations must not use up the five-iteration
budget either, or a multi-file app never reaches its commands (proof run 4).
"""
import inspect

from backend.apps.ai.processing import main_processor


# contract-test: direct surface=rest_api assertions=projects.sandbox.jobs
def test_only_all_inline_sandbox_iterations_are_free_and_bounded() -> None:
    free = main_processor._is_sandbox_free_iteration
    cap = main_processor.MAX_SANDBOX_FILE_ITERATIONS
    assert free(1, 1, 0)  # one file tool, run in the sandbox
    assert free(3, 3, cap - 1)
    assert not free(2, 1, 0)  # a search or code run in the same iteration uses the budget
    assert not free(1, 0, 0)  # device path or any other tool
    assert not free(0, 0, 0)  # no tool calls
    assert not free(1, 1, cap)  # bounded per turn
    assert cap >= 20  # an app of a few dozen files fits in one turn


def test_budget_checks_use_the_budget_counter_not_the_physical_iteration() -> None:
    source = inspect.getsource(main_processor.handle_main_processing)
    assert "for iteration in itertools.count(start_iteration):" in source
    assert "budget_iteration = iteration - sandbox_free_iterations" in source
    assert "if budget_iteration >= max_iterations_with_recovery:" in source
    # No limit check may still compare the physical counter with the budget constants.
    assert "iteration >= MAX_TOOL_CALL_ITERATIONS" not in source.replace("budget_iteration >=", "")
    assert "if iteration == MAX_TOOL_CALL_ITERATIONS" not in source
    assert "sandbox_inline_calls += 1" in source
