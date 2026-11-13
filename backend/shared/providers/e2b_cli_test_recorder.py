# backend/shared/providers/e2b_cli_test_recorder.py
#
# recorder_wrapper for Code Run test runs of kind "cli" (contract:
# docs/plans/agentic-tests-and-git-sync/contracts/test-run.md). The recorder
# program (terminal_test_recorder.py, standard library only) is not baked into
# the sandbox template: its source travels inside the wrapped argv as a
# `python3 -c` argument, so it works in E2B and on a remote worktree alike.

from __future__ import annotations

from pathlib import Path

from backend.shared.python_schemas.code_test_run import TestRunSpec

RECORDER_SOURCE_PATH = Path(__file__).with_name("terminal_test_recorder.py")


def recorder_source() -> str:
    return RECORDER_SOURCE_PATH.read_text(encoding="utf-8")


def cli_recorder_wrapper(spec: TestRunSpec) -> list[str]:
    """Return the argv that runs the spec's test command under the terminal recorder."""
    argv = ["python3", "-c", recorder_source()]
    if spec.preview_step:
        argv += ["--preview-step", spec.preview_step]
    return [*argv, "--", *spec.test_command.argv]
