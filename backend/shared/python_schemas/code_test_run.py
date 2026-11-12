# backend/shared/python_schemas/code_test_run.py
#
# Test-run contract for Code Run. One request schema (TestRunSpec) and one
# result schema (TestRunResult) are shared by the unit, browser and cli kinds,
# by E2B and by remote_source execution. Recorders (browser, cli) write the
# files described by RECORDER_* constants; parse_recorder_report() turns them
# into the result fields. Written contract: docs/plans/agentic-tests-and-git-sync/contracts/test-run.md

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TestKind = Literal["unit", "browser", "cli"]
TestTarget = Literal["e2b", "remote_source"]
RunStatus = Literal["passed", "failed", "error", "cancelled", "timed_out"]
StepStatus = Literal["passed", "failed", "skipped"]
EvidenceKind = Literal["video", "terminal_cast", "preview_frame", "trace", "report"]

MAX_REVISIONS = 500
MAX_COMMANDS = 20
MAX_ARGV = 128
MAX_STEPS = 500
MAX_TESTS = 2000
MAX_ERROR_CHARS = 4000

# Where recorders write, relative to the workspace root (E2B) or the worktree
# (remote). Everything under this directory is eligible evidence.
RECORDER_DIR = "outputs/test-run"
RECORDER_REPORT_FILE = f"{RECORDER_DIR}/report.json"
RECORDER_FILES: dict[str, tuple[str, str]] = {
    # evidence kind -> (relative path, mime type)
    "video": (f"{RECORDER_DIR}/video.webm", "video/webm"),
    "terminal_cast": (f"{RECORDER_DIR}/terminal.cast", "application/x-asciicast"),
    "preview_frame": (f"{RECORDER_DIR}/preview.png", "image/png"),
    "trace": (f"{RECORDER_DIR}/trace.zip", "application/zip"),
}
# Explicit caps for evidence files; larger files are skipped with a reason.
EVIDENCE_MAX_BYTES: dict[str, int] = {
    "video": 15_000_000,
    "terminal_cast": 2_000_000,
    "preview_frame": 2_000_000,
    "trace": 8_000_000,
    "report": 1_000_000,
}
TEST_RUN_MAX_TOTAL_ARTIFACT_BYTES = 40_000_000
TEST_RUN_MAX_ARTIFACTS = 12


def recorder_env(kind: str) -> dict[str, str]:
    """Environment every test command (and recorder) receives."""
    return {"OPENMATES_TEST_RUN_DIR": RECORDER_DIR, "OPENMATES_TEST_RUN_KIND": kind}


_REVISION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ProjectFileRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=255)
    revision: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _check(self) -> "ProjectFileRevision":
        if self.path.startswith(("/", "~")) or ".." in self.path.split("/"):
            raise ValueError("revision path must be project-relative")
        if not _REVISION_RE.match(self.revision):
            raise ValueError("invalid revision identifier")
        return self


class TestCommand(BaseModel):
    """One exact command as argv; use ["bash", "-lc", "..."] to opt into a shell."""

    __test__ = False  # not a pytest class
    model_config = ConfigDict(extra="forbid")

    argv: list[str] = Field(min_length=1, max_length=MAX_ARGV)
    cwd: str = "."
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @model_validator(mode="after")
    def _check(self) -> "TestCommand":
        if any(not part or "\x00" in part for part in self.argv):
            raise ValueError("argv entries must be non-empty strings")
        if self.cwd.startswith(("/", "~")) or ".." in self.cwd.split("/"):
            raise ValueError("cwd must be project-relative")
        return self


class ServerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: TestCommand
    ready_url: str = Field(pattern=r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?(/.*)?$")
    ready_timeout_seconds: int = Field(default=60, ge=1, le=300)


class TestRunSpec(BaseModel):
    """Request half of the contract. Validated before any sandbox exists."""

    __test__ = False
    model_config = ConfigDict(extra="forbid")

    kind: TestKind
    target: TestTarget | None = None  # None -> select_test_target()
    project_id: str | None = None
    source_id: str | None = None  # required for remote_source
    revisions: list[ProjectFileRevision] = Field(default_factory=list, max_length=MAX_REVISIONS)
    setup_commands: list[TestCommand] = Field(default_factory=list, max_length=MAX_COMMANDS)
    server: ServerSpec | None = None
    test_command: TestCommand
    preview_step: str | None = Field(default=None, max_length=200)
    enable_internet: bool = True

    @model_validator(mode="after")
    def _check(self) -> "TestRunSpec":
        paths = [item.path for item in self.revisions]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate revision path")
        if self.kind == "unit" and self.server is not None:
            raise ValueError("unit tests do not start a server")
        if self.target == "remote_source" and not (self.project_id and self.source_id):
            raise ValueError("remote_source requires project_id and source_id")
        return self


def select_test_target(
    requested: TestTarget | None,
    *,
    focus_has_remote_run_source: bool,
) -> TestTarget:
    """Pick the execution target. An explicit request always wins.

    Default: remote_source when the active Project focus has a connected remote
    source that grants run_command; e2b otherwise (hosted Projects).
    """
    if requested is not None:
        return requested
    return "remote_source" if focus_has_remote_run_source else "e2b"


class TestStep(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=300)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    status: StepStatus
    error: str | None = Field(default=None, max_length=MAX_ERROR_CHARS)
    is_preview: bool = False
    command: str | None = Field(default=None, max_length=1000)  # cli kind: command entered
    output: str | None = Field(default=None, max_length=MAX_ERROR_CHARS)  # cli kind: output produced

    @model_validator(mode="after")
    def _order(self) -> "TestStep":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms before start_ms")
        return self


class TestCaseResult(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    status: Literal["passed", "failed", "skipped"]
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=MAX_ERROR_CHARS)


class EvidenceRef(BaseModel):
    """Reference to a stored run artifact; bytes live in the artifact store."""

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    path: str  # normalized artifact path, e.g. outputs/test-run/video.webm
    mime_type: str
    size_bytes: int = Field(ge=0)
    asset_id: str | None = None  # filled after the artifact is persisted
    at_step: int | None = Field(default=None, ge=0)  # preview_frame: index of the step


class TestRunResult(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")

    kind: TestKind
    target: TestTarget
    status: RunStatus
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    revisions: list[ProjectFileRevision] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)  # Project snapshot paths the run executed
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    tests: list[TestCaseResult] = Field(default_factory=list, max_length=MAX_TESTS)
    steps: list[TestStep] = Field(default_factory=list, max_length=MAX_STEPS)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    preview_step_index: int | None = None
    error: str | None = Field(default=None, max_length=MAX_ERROR_CHARS)


def validate_test_run_spec(raw: dict[str, Any]) -> TestRunSpec:
    """Validate a raw tool/REST payload; raises pydantic.ValidationError."""
    return TestRunSpec.model_validate(raw)


def parse_recorder_report(text: str) -> tuple[list[TestCaseResult], list[TestStep], int | None]:
    """Parse RECORDER_REPORT_FILE content into (tests, steps, preview_step_index).

    The report is untrusted sandbox output: malformed content raises ValueError
    (callers surface it as an error result rather than guessing).
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("test report is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("test report must be a JSON object")
    raw_tests = payload.get("tests", [])
    raw_steps = payload.get("steps", [])
    if not isinstance(raw_tests, list) or not isinstance(raw_steps, list):
        raise ValueError("tests and steps must be lists")
    tests = [TestCaseResult.model_validate(item) for item in raw_tests[:MAX_TESTS]]
    steps = [TestStep.model_validate(item) for item in raw_steps[:MAX_STEPS]]
    preview = payload.get("preview_step_index")
    if preview is None:
        preview = next((index for index, step in enumerate(steps) if step.is_preview), None)
    if preview is not None and (isinstance(preview, bool) or not isinstance(preview, int) or not 0 <= preview < len(steps)):
        raise ValueError("preview_step_index out of range")
    return tests, steps, preview


def count_tests(tests: list[TestCaseResult]) -> tuple[int, int, int]:
    return (
        sum(1 for t in tests if t.status == "passed"),
        sum(1 for t in tests if t.status == "failed"),
        sum(1 for t in tests if t.status == "skipped"),
    )


def result_is_current(result: TestRunResult, current: list[ProjectFileRevision]) -> bool:
    """A result counts as passing only if it ran against exactly the current revisions."""
    ran = {item.path: item.revision for item in result.revisions}
    now = {item.path: item.revision for item in current}
    return ran == now
