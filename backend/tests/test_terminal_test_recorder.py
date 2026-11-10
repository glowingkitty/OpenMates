# backend/tests/test_terminal_test_recorder.py
#
# Runs the standard-library terminal recorder against small shell scripts under a
# real pseudo-terminal and checks the asciicast, the step report and truncation.

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.shared.providers.e2b_cli_test_recorder import cli_recorder_wrapper, recorder_source
from backend.shared.providers.terminal_test_recorder import StepTracker
from backend.shared.python_schemas.code_test_run import TestRunSpec, parse_recorder_report

START = "\\033]777;openmates-step;%s\\007"
END = "\\033]777;openmates-step-end;%s\\007"


def record(tmp_path: Path, script: str, *options: str) -> tuple[int, list[str], dict]:
    out = tmp_path / "outputs" / "test-run"
    out.mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, "-c", recorder_source(), *options, "--", "bash", "-c", script],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "OPENMATES_TEST_RUN_DIR": "outputs/test-run"},
        capture_output=True, timeout=60,
    )
    cast = (out / "terminal.cast").read_text(encoding="utf-8").splitlines()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    return proc.returncode, cast, report


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_marked_steps_and_cast(tmp_path: Path) -> None:
    script = (
        f"printf '{START}' 'recipes add Pancakes'; echo 'added Pancakes';"
        f"printf '{END}' 0; printf '{START}' 'recipes list'; echo 'Pancakes';"
        f"printf '{END}' 0"
    )
    code, cast, report = record(tmp_path, script, "--preview-step", "recipes list")
    assert code == 0
    header = json.loads(cast[0])
    assert header["version"] == 2 and header["width"] > 0
    events = [json.loads(line) for line in cast[1:]]
    assert all(e[1] == "o" for e in events)
    assert "added Pancakes" in "".join(e[2] for e in events)
    tests, steps, preview = parse_recorder_report(json.dumps(report))
    assert [s.command for s in steps] == ["recipes add Pancakes", "recipes list"]
    assert steps[0].output == "added Pancakes\n" and steps[1].output == "Pancakes\n"
    assert all(s.status == "passed" for s in steps) and preview == 1
    assert steps[0].end_ms <= steps[1].start_ms + 1
    assert tests[0].status == "passed"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_failed_step_status_and_exit_code(tmp_path: Path) -> None:
    script = f"printf '{START}' 'bad'; echo boom; printf '{END}' 2; printf '{START}' 'next'; echo ok; exit 3"
    code, _, report = record(tmp_path, script)
    assert code == 3
    assert [s["status"] for s in report["steps"]] == ["failed", "failed"]
    assert report["steps"][0]["error"] == "exit code 2"
    assert report["tests"][0]["status"] == "failed"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_no_markers_gives_one_step_per_test_command(tmp_path: Path) -> None:
    code, _, report = record(tmp_path, "echo hello; echo world")
    assert code == 0
    (step,) = report["steps"]
    assert step["command"] == "bash -c echo hello; echo world"
    assert step["output"] == "hello\nworld"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_marker_split_across_chunks() -> None:
    tracker = StepTracker("cmd", None)
    tracker.feed("\x1b]777;openmates-st", 1)
    tracker.feed("ep;ls -l\x07out\n", 2)
    steps = tracker.finish(0, 3)
    assert steps[0]["command"] == "ls -l" and steps[0]["output"] == "out\n"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_output_truncated_with_marker(tmp_path: Path) -> None:
    script = f"printf '{START}' big; head -c 9000 /dev/zero | tr '\\\\0' 'x'; echo"
    _, _, report = record(tmp_path, script)
    output = report["steps"][0]["output"]
    assert len(output) <= 4000 and "step output truncated" in output
    parse_recorder_report(json.dumps(report))


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_cast_truncated_with_marker(tmp_path: Path) -> None:
    script = "for i in $(seq 1 400); do head -c 8000 /dev/zero | tr '\\0' 'y'; echo; done"
    _, cast, _ = record(tmp_path, script)
    size = sum(len(line.encode()) + 1 for line in cast)
    assert size <= 2_000_000
    assert "terminal cast truncated" in json.loads(cast[-1])[2]


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_wrapper_argv_embeds_recorder() -> None:
    spec = TestRunSpec.model_validate({
        "kind": "cli", "target": "e2b", "preview_step": "list",
        "test_command": {"argv": ["bash", "run.sh"]},
    })
    argv = cli_recorder_wrapper(spec)
    assert argv[:2] == ["python3", "-c"] and "openmates-step" in argv[2]
    assert argv[3:] == ["--preview-step", "list", "--", "bash", "run.sh"]
