# backend/tests/test_code_test_run.py
#
# Unit tests for the Code Run test-run contract: schema validation, default
# target selection, result building and the unit-kind E2B runner flow. The E2B
# SDK is replaced at the Sandbox boundary only, as in test_e2b_code_runner.py.

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.apps.code.test_run_target import pick_remote_run_source, resolve_test_run_target
from backend.shared.providers.e2b_code_runner import (
    CodeRunFile,
    _artifact_discovery_command,
    _parse_artifact_discovery,
)
from backend.shared.providers.e2b_test_runner import (
    build_result_from_run,
    command_to_shell,
    run_tests_in_e2b,
)
from backend.shared.python_schemas.code_test_run import (
    ProjectFileRevision,
    TestRunResult,
    TestRunSpec,
    parse_recorder_report,
    result_is_current,
    select_test_target,
    validate_test_run_spec,
)


def _spec(**overrides):
    base = {"kind": "unit", "test_command": {"argv": ["pytest", "-q"]}}
    base.update(overrides)
    return base


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_spec_validation_accepts_unit_and_rejects_bad_input() -> None:
    spec = validate_test_run_spec(_spec(setup_commands=[{"argv": ["pip", "install", "-r", "requirements.txt"]}]))
    assert spec.kind == "unit" and spec.target is None
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(kind="load"))
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(test_command={"argv": []}))
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(test_command={"argv": ["pytest"], "cwd": "../x"}))
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(revisions=[{"path": "a.py", "revision": "r1"}, {"path": "a.py", "revision": "r2"}]))
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(server={"command": {"argv": ["npm", "start"]}, "ready_url": "http://localhost:3000"}))
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(kind="browser", server={"command": {"argv": ["npm", "start"]}, "ready_url": "http://evil.example/"}))
    with pytest.raises(ValidationError):
        validate_test_run_spec(_spec(target="remote_source"))


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_default_target_selection() -> None:
    assert select_test_target(None, focus_has_remote_run_source=False) == "e2b"
    assert select_test_target(None, focus_has_remote_run_source=True) == "remote_source"
    assert select_test_target("e2b", focus_has_remote_run_source=True) == "e2b"
    assert select_test_target("remote_source", focus_has_remote_run_source=False) == "remote_source"


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_pick_remote_run_source_skips_offline_revoked_and_unprivileged() -> None:
    sources = [
        {"source_id": "a", "status": "offline", "capabilities": ["run_command"]},
        {"source_id": "b", "status": "connected", "capabilities": ["read"]},
        {"source_id": "c", "status": "revoked", "capabilities": ["run_command"]},
        {"source_id": "d", "status": "connected", "capabilities": ["run_command"]},
    ]
    assert pick_remote_run_source(sources) == "d"
    assert pick_remote_run_source(sources[:3]) is None


class _FakeProject:
    def __init__(self, sources):
        self.sources = sources

    async def list_sources(self, project_id, user_id, team_id=None):
        return self.sources


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
@pytest.mark.asyncio
async def test_resolve_target_uses_focus_remote_source_and_honors_override() -> None:
    directus = SimpleNamespace(project=_FakeProject([{"source_id": "s1", "status": "connected", "capabilities": ["run_command"]}]))
    focus = {"project_id": "p1"}
    spec = validate_test_run_spec(_spec())
    assert await resolve_test_run_target(spec, directus_service=directus, focus=focus, user_id="u") == ("remote_source", "p1", "s1")
    override = validate_test_run_spec(_spec(target="e2b"))
    assert await resolve_test_run_target(override, directus_service=directus, focus=focus, user_id="u") == ("e2b", "p1", None)
    assert await resolve_test_run_target(spec, directus_service=directus, focus=None, user_id="u") == ("e2b", None, None)


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_recorder_report_parsing_and_preview_step() -> None:
    report = json.dumps({
        "tests": [{"name": "login", "status": "passed", "duration_ms": 10}],
        "steps": [
            {"name": "open", "start_ms": 0, "end_ms": 5, "status": "passed"},
            {"name": "submit", "start_ms": 5, "end_ms": 9, "status": "passed", "is_preview": True},
        ],
    })
    tests, steps, preview = parse_recorder_report(report)
    assert len(tests) == 1 and len(steps) == 2 and preview == 1
    with pytest.raises(ValueError):
        parse_recorder_report("not json")
    with pytest.raises(ValueError):
        parse_recorder_report(json.dumps({"steps": [], "preview_step_index": 3}))
    with pytest.raises(ValueError):
        parse_recorder_report(json.dumps({"steps": [{"name": "x", "start_ms": 5, "end_ms": 1, "status": "passed"}]}))


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_result_is_stale_when_revisions_differ() -> None:
    ran = [ProjectFileRevision(path="a.py", revision="r1")]
    result = TestRunResult(kind="unit", target="e2b", status="passed", revisions=ran)
    assert result_is_current(result, [ProjectFileRevision(path="a.py", revision="r1")])
    assert not result_is_current(result, [ProjectFileRevision(path="a.py", revision="r2")])
    assert not result_is_current(result, ran + [ProjectFileRevision(path="b.py", revision="r1")])


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_build_result_error_when_non_unit_has_no_report_and_when_report_malformed() -> None:
    spec = TestRunSpec.model_validate(_spec(kind="browser"))
    missing = build_result_from_run(spec, target="e2b", exit_code=0, duration_ms=1, command_steps=[],
                                    report_text=None, artifacts=[], error=None)
    assert missing.status == "error"
    bad = build_result_from_run(TestRunSpec.model_validate(_spec()), target="e2b", exit_code=0, duration_ms=1,
                                command_steps=[], report_text="{", artifacts=[], error=None)
    assert bad.status == "error"


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_build_result_failed_test_overrides_zero_exit_and_collects_evidence() -> None:
    spec = TestRunSpec.model_validate(_spec(kind="browser"))
    report = json.dumps({"tests": [{"name": "t", "status": "failed", "error": "boom"}],
                         "steps": [{"name": "s", "start_ms": 0, "end_ms": 1, "status": "failed", "is_preview": True}]})
    artifacts = [{"normalized_path": "outputs/test-run/video.webm", "size_bytes": 123}]
    result = build_result_from_run(spec, target="e2b", exit_code=0, duration_ms=9, command_steps=[],
                                   report_text=report, artifacts=artifacts, error=None)
    assert result.status == "failed" and result.failed == 1
    assert [e.kind for e in result.evidence] == ["video"]
    assert result.preview_step_index == 0


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_command_to_shell_quotes_argv_and_sets_env() -> None:
    spec = TestRunSpec.model_validate(_spec(test_command={"argv": ["pytest", "-k", "a b"], "cwd": "web"}))
    line = command_to_shell(spec.test_command, {"OPENMATES_TEST_RUN_KIND": "unit"})
    assert line.startswith("cd /home/user/openmates-run/web && OPENMATES_TEST_RUN_KIND=unit pytest -k 'a b'")


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_test_run_discovery_allows_video_and_cast_with_caps_only_for_test_runs() -> None:
    normal = _artifact_discovery_command()
    test_run = _artifact_discovery_command(test_run=True)
    assert ".webm" not in normal and ".cast" not in normal
    assert ".webm" in test_run and ".cast" in test_run and "15000000" in test_run
    artifacts, _ = _parse_artifact_discovery(
        json.dumps({"artifacts": [{"path": "outputs/test-run/video.webm", "normalized_path": "outputs/test-run/video.webm",
                                   "mime_type": "video/webm", "kind": "video", "size_bytes": 9_000_000, "content_base64": "AA=="}],
                    "skipped": []}),
        max_artifacts=12, max_artifact_bytes=15_000_000,
    )
    assert len(artifacts) == 1


class _Handle:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code

    def wait(self, on_stdout=None, on_stderr=None):
        if on_stdout:
            on_stdout("ran\n")
        return SimpleNamespace(exit_code=self.exit_code)

    def kill(self) -> bool:
        return True


class _Sandbox:
    sandbox_id = "sb-1"
    instances: list["_Sandbox"] = []
    fail_substring: str | None = None
    report: str = ""

    @classmethod
    def create(cls, **kwargs):
        instance = cls()
        instance.create_kwargs = kwargs
        instance.background_commands: list[str] = []
        instance.written: list[str] = []
        instance.files = SimpleNamespace(write_files=lambda items: instance.written.extend(i["path"] for i in items))
        instance.commands = SimpleNamespace(run=instance._run)
        cls.instances.append(instance)
        return instance

    def _run(self, command, background=False, timeout=None):
        if background:
            self.background_commands.append(command)
            failing = self.fail_substring and self.fail_substring in command
            return _Handle(1 if failing else 0)
        if "test -f" in command:
            return SimpleNamespace(stdout=type(self).report)
        if "OPENMATES_CODE_RUN_DISCOVER_OUTPUTS" in command:
            return SimpleNamespace(stdout=json.dumps({"artifacts": [], "skipped": []}))
        return SimpleNamespace(stdout="")

    def kill(self) -> None:
        self.killed = True


@pytest.fixture(autouse=True)
def _fake_e2b(monkeypatch: pytest.MonkeyPatch):
    _Sandbox.instances = []
    _Sandbox.fail_substring = None
    _Sandbox.report = ""
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=_Sandbox))
    monkeypatch.delenv("E2B_CODE_RUN_TEMPLATE", raising=False)
    monkeypatch.delenv("E2B_APPLICATION_PREVIEW_TEMPLATE", raising=False)


def _files():
    return [CodeRunFile(path="app/test_a.py", language="python", content="def test_a(): pass"),
            CodeRunFile(path="requirements.txt", language="", content="pytest")]


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
def test_unit_run_executes_setup_then_tests_and_names_revisions() -> None:
    spec = TestRunSpec.model_validate(_spec(
        revisions=[{"path": "app/test_a.py", "revision": "r1"}, {"path": "requirements.txt", "revision": "r2"}],
        setup_commands=[{"argv": ["pip", "install", "-r", "requirements.txt"]}],
    ))
    _Sandbox.report = json.dumps({"tests": [{"name": "test_a", "status": "passed"}], "steps": []})
    outcome = run_tests_in_e2b(_files(), spec, lambda _k, _t: None, "key")
    sandbox = _Sandbox.instances[0]
    assert sandbox.written == ["/home/user/openmates-run/app/test_a.py", "/home/user/openmates-run/requirements.txt"]
    assert len(sandbox.background_commands) == 2
    assert "pip install -r requirements.txt" in sandbox.background_commands[0]
    assert "pytest -q" in sandbox.background_commands[1]
    assert outcome.result.status == "passed" and outcome.result.passed == 1
    assert [s.status for s in outcome.result.steps] == ["passed", "passed"]
    assert {r.path: r.revision for r in outcome.result.revisions} == {"app/test_a.py": "r1", "requirements.txt": "r2"}
    assert getattr(sandbox, "killed", False)


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_unit_run_stops_after_failed_setup_and_reports_error_status() -> None:
    _Sandbox.fail_substring = "pip install"
    spec = TestRunSpec.model_validate(_spec(setup_commands=[{"argv": ["pip", "install", "x"]}]))
    outcome = run_tests_in_e2b(_files(), spec, lambda _k, _t: None, "key")
    assert len(_Sandbox.instances[0].background_commands) == 1
    assert outcome.result.status == "error"
    assert outcome.result.steps[0].status == "failed"


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_unit_run_failing_tests_is_failed_and_mismatched_revisions_rejected() -> None:
    _Sandbox.fail_substring = "pytest"
    spec = TestRunSpec.model_validate(_spec())
    assert run_tests_in_e2b(_files(), spec, lambda _k, _t: None, "key").result.status == "failed"
    wrong = TestRunSpec.model_validate(_spec(revisions=[{"path": "other.py", "revision": "r1"}]))
    with pytest.raises(ValueError):
        run_tests_in_e2b(_files(), wrong, lambda _k, _t: None, "key")


# contract-test: supporting surface=rest_api assertions=code-run.tests.project-snapshot
def test_browser_run_starts_server_waits_for_readiness_then_tests() -> None:
    spec = TestRunSpec.model_validate(_spec(
        kind="browser",
        server={"command": {"argv": ["npm", "run", "dev"]}, "ready_url": "http://localhost:5173/"},
        test_command={"argv": ["npx", "playwright", "test"]},
    ))
    _Sandbox.report = json.dumps({"tests": [], "steps": [{"name": "s", "start_ms": 0, "end_ms": 1, "status": "passed"}]})
    outcome = run_tests_in_e2b(_files(), spec, lambda _k, _t: None, "key")
    commands = _Sandbox.instances[0].background_commands
    assert "setsid" in commands[0] and "npm run dev" in commands[0]
    assert "curl" in commands[1] and "localhost:5173" in commands[1]
    assert "playwright test" in commands[2]
    assert outcome.result.status == "passed"
