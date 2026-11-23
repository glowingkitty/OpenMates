# contract-test-file: infrastructure
"""Inline sandbox file tools keep the turn's iteration budget, like device-path pauses do.

On the device path every Project file operation pauses the turn and its continuation
starts a fresh budget. Inline sandbox operations must not use up the five-iteration
budget either, or a multi-file app never reaches its commands (proof run 4).
"""
import inspect

import pytest

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

def test_same_turn_resume_keeps_the_sandbox_allowance_already_used() -> None:
    """Proof run 8: four free sandbox reads, then a code-run resume restarted at budget 6/7."""
    resumed = main_processor._resumed_sandbox_free_iterations
    assert resumed(None, 0) == 0  # fresh turn
    assert resumed({"next_iteration": 5}, 5) == 0  # checkpoint written before this rule
    assert resumed({"sandbox_free_iterations": 4}, 5) == 4
    over_cap = main_processor.MAX_SANDBOX_FILE_ITERATIONS + 1
    # (allowance, resume iteration): negative, more than the iterations run, wrong types, over the cap
    for bad, start in ((-1, 5), (6, 5), ("4", 5), (True, 5), (over_cap, over_cap + 5)):
        with pytest.raises(main_processor.RequiredRecoveryOutputError):
            resumed({"sandbox_free_iterations": bad}, start)

def test_checkpoint_carries_the_allowance_and_the_loop_restores_it() -> None:
    source = inspect.getsource(main_processor.handle_main_processing)
    assert '"sandbox_free_iterations": sandbox_free_iterations,' in source
    assert "sandbox_free_iterations = _resumed_sandbox_free_iterations(resume_checkpoint, start_iteration)" in source

def test_sandbox_command_passes_and_repeated_sandbox_reads_keep_the_budget() -> None:
    """Proof run 20: three install commands and one repeated sandbox read used the whole
    four-pass budget, so the requested test never ran. Sandbox commands and repeats of an
    inline sandbox file call now use the sandbox allowance instead."""
    source = inspect.getsource(main_processor.handle_main_processing)
    gate = source.index("parsed_args = _pts.use_project_sandbox(parsed_args)")
    counter = source.index('if app_id != "system" and not project_sandbox_command:')
    assert gate < counter  # decided before the research skill budget counts the call
    assert "project_sandbox_command = sandbox_free_iterations < MAX_SANDBOX_FILE_ITERATIONS" in source
    assert source.count("_pts.use_project_sandbox(") == 1
    assert "if call_hash in sandbox_inline_call_hashes:" in source
    assert "sandbox_inline_call_hashes.add(call_hash)" in source
    # A pass of sandbox commands pauses for their results: the free check runs before the
    # same-turn checkpoint so the resume carries the allowance it used.
    pause = source.index("if async_batch_jobs:\n")
    checkpoint = source.index('"sandbox_free_iterations": sandbox_free_iterations,')
    free_check = source.index("_is_sandbox_free_iteration(", pause)
    assert pause < free_check < checkpoint
