# backend/shared/providers/e2b_test_runner.py
#
# E2B executor for the Code Run test-run contract (see
# backend/shared/python_schemas/code_test_run.py). Uploads a Project snapshot,
# runs setup commands, optionally starts a server and waits for readiness, runs
# the test command, then collects the structured result and evidence files.
# The `unit` kind is fully handled here. `browser` and `cli` use the same flow;
# their recorders only have to write the files named in RECORDER_FILES and
# RECORDER_REPORT_FILE, and may be wrapped around the test command via
# `recorder_wrapper` (a callable returning the argv to run instead).

from __future__ import annotations

import os
import shlex
import time
from dataclasses import dataclass
from typing import Callable, cast

from backend.shared.providers.e2b_code_runner import (
    CODE_RUN_TEMPLATE_ENV,
    MAX_OUTPUT_CHARS,
    WORKSPACE_DIR,
    CancelCallback,
    CodeRunCancelled,
    CodeRunFile,
    OutputCallback,
    OutputKind,
    _discover_output_artifacts,
    _emit,
    _file_payload,
    _run_interruptible_command,
)
from backend.shared.python_schemas.code_test_run import (
    RECORDER_FILES,
    RECORDER_REPORT_FILE,
    EvidenceKind,
    EvidenceRef,
    TestCaseResult,
    TestCommand,
    TestRunResult,
    TestRunSpec,
    TestStep,
    count_tests,
    parse_recorder_report,
    recorder_env,
)

APPLICATION_PREVIEW_TEMPLATE_ENV = "E2B_APPLICATION_PREVIEW_TEMPLATE"
PLAYWRIGHT_BROWSERS_PATH = "/home/user/.cache/openmates-application-capture/browsers"
SERVER_LOG = "/tmp/openmates-test-server.log"
SERVER_PID = "/tmp/openmates-test-server.pid"

RecorderWrapper = Callable[[TestRunSpec], list[str]]


@dataclass(frozen=True)
class TestRunOutcome:
    __test__ = False
    result: TestRunResult
    artifacts: list[dict[str, object]]
    skipped_artifacts: list[dict[str, str]]
    sandbox_id: str | None
    duration_seconds: float
    output_truncated: bool


def command_to_shell(command: TestCommand, env: dict[str, str] | None = None) -> str:
    """Render a validated argv command as one cd + exec shell line."""
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in (env or {}).items())
    argv = " ".join(shlex.quote(part) for part in command.argv)
    cwd = shlex.quote(f"{WORKSPACE_DIR}/{command.cwd}".rstrip("/."))
    return f"cd {cwd} && {prefix + ' ' if prefix else ''}{argv}"


def server_start_shell(command_line: str) -> str:
    """Start the server detached so it outlives this step and is torn down with the sandbox."""
    return f"nohup setsid bash -lc {shlex.quote(command_line)} > {SERVER_LOG} 2>&1 & echo $! > {SERVER_PID}"


def readiness_shell(url: str, timeout_seconds: int) -> str:
    return (
        f"for i in $(seq 1 {timeout_seconds * 4}); do "
        f"curl -fsS -o /dev/null {shlex.quote(url)} && exit 0; sleep 0.25; done; "
        f"echo 'server did not become ready' >&2; tail -n 40 {SERVER_LOG} >&2; exit 1"
    )


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _error_text(exit_code: int | None, label: str) -> str:
    return f"{label} exited with code {exit_code}"


def build_result_from_run(
    spec: TestRunSpec,
    *,
    target: str,
    exit_code: int | None,
    duration_ms: int,
    command_steps: list[TestStep],
    report_text: str | None,
    artifacts: list[dict[str, object]],
    error: str | None,
    timed_out: bool = False,
    file_paths: list[str] | None = None,
) -> TestRunResult:
    """Merge command steps with the recorder report and evidence into one result.

    A missing report is valid for unit runs (status comes from the exit code).
    A present but malformed report is an error result, never a silent pass.
    """
    tests: list[TestCaseResult] = []
    steps = list(command_steps)
    preview_index: int | None = None
    report_error: str | None = None
    if report_text is not None:
        try:
            tests, report_steps, report_preview = parse_recorder_report(report_text)
            offset = len(steps)
            steps.extend(report_steps)
            preview_index = None if report_preview is None else report_preview + offset
        except ValueError as exc:
            report_error = f"Invalid test report: {exc}"
    elif spec.kind != "unit" and exit_code in (None, 0) and not error:
        report_error = f"{spec.kind} test produced no {RECORDER_REPORT_FILE}"

    passed, failed, skipped = count_tests(tests)
    if error or report_error:
        status = "timed_out" if timed_out else "error"
    elif exit_code in (None, 0) and failed == 0:
        status = "passed"
    else:
        status = "failed"

    evidence: list[EvidenceRef] = []
    by_path = {str(item.get("normalized_path")): item for item in artifacts}
    for kind, (path, mime_type) in RECORDER_FILES.items():
        item = by_path.get(path)
        if item is None:
            continue
        size = item.get("size_bytes")
        evidence.append(EvidenceRef(
            kind=cast(EvidenceKind, kind),
            path=path,
            mime_type=mime_type,
            size_bytes=size if isinstance(size, int) else 0,
            at_step=preview_index if kind == "preview_frame" else None,
        ))
    return TestRunResult(
        kind=spec.kind,
        target="e2b" if target == "e2b" else "remote_source",
        status=status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        revisions=list(spec.revisions),
        file_paths=sorted(file_paths or []),
        passed=passed,
        failed=failed,
        skipped=skipped,
        tests=tests,
        steps=steps,
        evidence=evidence,
        preview_step_index=preview_index,
        error=error or report_error,
    )


def run_tests_in_e2b(
    files: list[CodeRunFile],
    spec: TestRunSpec,
    on_output: OutputCallback,
    api_key: str,
    should_cancel: CancelCallback | None = None,
    recorder_wrapper: RecorderWrapper | None = None,
) -> TestRunOutcome:
    """Run a validated TestRunSpec over `files` in one disposable E2B sandbox."""
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc
    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")
    revision_paths = {item.path for item in spec.revisions}
    file_paths = {file.path for file in files}
    if revision_paths and revision_paths != file_paths:
        raise ValueError("Uploaded files do not match the supplied revisions")

    output_chars = 0
    truncated = False
    sandbox = None

    def stream(kind: OutputKind, text: str) -> None:
        nonlocal output_chars, truncated
        if output_chars >= MAX_OUTPUT_CHARS:
            truncated = True
            return
        chunk = text[: MAX_OUTPUT_CHARS - output_chars]
        output_chars += len(chunk)
        truncated = truncated or len(chunk) < len(text)
        _emit(on_output, kind, chunk)

    def check_cancel() -> None:
        if should_cancel and should_cancel():
            raise CodeRunCancelled("Code run cancelled by user")

    steps: list[TestStep] = []

    def run_step(name: str, shell_line: str, timeout: int, started: float) -> int | None:
        check_cancel()
        _emit(on_output, "status", f"{name}...\n")
        begin = _ms(started)
        code = _run_interruptible_command(sandbox, shell_line, timeout, stream, should_cancel)
        ok = code in (None, 0)
        steps.append(TestStep(
            name=name, start_ms=begin, end_ms=max(begin, _ms(started)),
            status="passed" if ok else "failed",
            error=None if ok else _error_text(code, name),
        ))
        return code

    try:
        _emit(on_output, "status", "Starting sandbox...\n")
        template = os.getenv(APPLICATION_PREVIEW_TEMPLATE_ENV) if spec.kind == "browser" else None
        template = template or os.getenv(CODE_RUN_TEMPLATE_ENV)
        options: dict[str, object] = {"template": template} if template else {}
        if template and spec.kind == "browser":
            options["envs"] = {"PLAYWRIGHT_BROWSERS_PATH": PLAYWRIGHT_BROWSERS_PATH}
        sandbox = Sandbox.create(
            **options, api_key=api_key, secure=True,
            allow_internet_access=spec.enable_internet,
            network={"allow_public_traffic": False},
        )
        sandbox_id = getattr(sandbox, "sandbox_id", None) or getattr(sandbox, "id", None)
        check_cancel()

        _emit(on_output, "status", f"Uploading {len(files)} files...\n")
        dirs = sorted({f"{WORKSPACE_DIR}/{f.path.rsplit('/', 1)[0]}" for f in files if "/" in f.path})
        sandbox.commands.run("mkdir -p " + " ".join(shlex.quote(p) for p in [WORKSPACE_DIR, f"{WORKSPACE_DIR}/outputs/test-run", *dirs]))
        sandbox.files.write_files([{"path": f"{WORKSPACE_DIR}/{f.path}", "data": _file_payload(f)} for f in files])
        started = time.monotonic()
        env = recorder_env(spec.kind)

        def finish(exit_code: int | None, error: str | None, timed_out: bool = False) -> TestRunOutcome:
            artifacts, skipped = _discover_output_artifacts(sandbox, test_run=True)
            report_text = _read_report(sandbox)
            result = build_result_from_run(
                spec, target="e2b", exit_code=exit_code, duration_ms=_ms(started),
                command_steps=steps, report_text=report_text, artifacts=artifacts,
                error=error, timed_out=timed_out,
                file_paths=sorted(file_paths),
            )
            return TestRunOutcome(result, artifacts, skipped, sandbox_id, time.monotonic() - started, truncated)

        for command in spec.setup_commands:
            label = "Installing/setup: " + " ".join(command.argv)[:120]
            code = run_step(label, command_to_shell(command, env), command.timeout_seconds, started)
            if code not in (None, 0):
                return finish(code, f"Setup command failed with exit code {code}; tests were not run.")

        if spec.server is not None:
            server = spec.server
            code = run_step("Starting server", server_start_shell(command_to_shell(server.command, env)), 20, started)
            if code not in (None, 0):
                return finish(code, "Server could not be started.")
            code = run_step("Waiting for server", readiness_shell(server.ready_url, server.ready_timeout_seconds),
                            server.ready_timeout_seconds + 10, started)
            if code not in (None, 0):
                return finish(code, "Server did not become ready.")

        test_command = spec.test_command
        if recorder_wrapper is not None:
            test_command = test_command.model_copy(update={"argv": recorder_wrapper(spec)})
        code = run_step("Running tests", command_to_shell(test_command, env), test_command.timeout_seconds, started)
        error = None
        timed_out = code == 124  # GNU timeout exit code
        if timed_out:
            error = f"Test command timed out after {test_command.timeout_seconds}s"
        return finish(code, error, timed_out)
    finally:
        if sandbox is not None:
            for method_name in ("kill", "close"):
                method = getattr(sandbox, method_name, None)
                if callable(method):
                    method()
                    break


def _read_report(sandbox: object) -> str | None:
    """Read the recorder/test report if the run produced one."""
    path = f"{WORKSPACE_DIR}/{RECORDER_REPORT_FILE}"
    result = sandbox.commands.run(f"test -f {shlex.quote(path)} && head -c 1000000 {shlex.quote(path)}; true")
    text = str(getattr(result, "stdout", "") or "")
    return text or None

