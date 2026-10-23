# contract-test-file: tooling
"""Offline privacy, correlation and process-lifecycle checks; no Docker/API calls."""

import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from scripts import ci_web_search_diagnostics as diagnostic

CHAT = "11111111-1111-4111-8111-111111111111"
MESSAGE = "22222222-2222-4222-8222-222222222222"
TASK = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
TITLE = next(iter(diagnostic.CASES))
SECRET = "PRIVATE_SENTINEL_credentials_prompt_cookie_url"
PROVENANCE = {"source_commit": "a" * 40, "harness_commit": "b" * 40, "run_id": "123"}


def line(service, logger, message, second=11, **extra):
    record = {"name": logger, "level": "INFO", "message": message, **extra}
    return f'{service}-1  | 2026-10-23T00:00:{second:02d}.000000000Z {json.dumps(record)}\n'.encode()


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / "frontend/apps/web_app/test-results/ci-0"
    root.mkdir(parents=True)
    attachment = root / "case/attachments/correlation.json"
    attachment.parent.mkdir(parents=True)
    browser = {"schema": 1, "title": TITLE, "retry": 0, "group": diagnostic.CASES[TITLE],
               "chat_id": CHAT, "flags": [], "events": [
                   {"utc": "2026-10-23T00:00:10Z", "direction": "sent", "event": "chat_turn_admit",
                    "chat_id": CHAT, "message_id": MESSAGE, "turn_id": OTHER,
                    "marker_present": True, "expected_group_match": True},
                   {"utc": "2026-10-23T00:00:12Z", "direction": "received", "event": "ai_task_initiated",
                    "chat_id": CHAT, "message_id": MESSAGE, "task_id": TASK},
               ]}
    attachment.write_text(json.dumps(browser))
    result = {"status": "failed", "retry": 0, "startTime": "2026-10-23T00:00:10Z", "duration": 10000,
              "attachments": [{"name": diagnostic.ATTACHMENT, "contentType": "application/json", "path": str(attachment)}]}
    report = {"suites": [{"suites": [{"specs": [{"file": diagnostic.SPEC, "title": TITLE, "tests": [{"results": [result]}]}]}]}]}
    capture = diagnostic.Capture(tmp_path, dict(PROVENANCE))
    capture.started, capture.ended = "2026-10-23T00:00:00Z", "2026-10-23T00:01:00Z"
    for raw in (
        line("api", diagnostic.API_LOGGER, f"Applied dev E2E test mock marker for message {MESSAGE}", 10),
        line("api", diagnostic.API_LOGGER, f"[PERF] In-process ai.ask dispatch took 0.001s, Task ID: {TASK} for user_id={SECRET}, chat_id={CHAT}, message_id={MESSAGE}"),
        line("ai-worker", diagnostic.ASK_LOGGER, f"[Task ID: {TASK}] LIVE MOCK: group='{diagnostic.CASES[TITLE]}' — full pipeline with cached API responses", 12),
        line("ai-worker", diagnostic.ASK_LOGGER, f"[Task ID: {TASK}] Starting preprocessing step... {SECRET}", 13),
        line("ai-worker", diagnostic.ASK_LOGGER,
             f'[Task ID: {TASK}] failed {SECRET}', 14, level="ERROR", headers={"cookie": SECRET},
             exc_info=f'Traceback (most recent call last):\nFile "/app/backend/apps/ai/tasks/ask_skill_task.py", line 3370, in preprocess\nMockCacheMiss: https://secret.invalid/{SECRET}'),
    ):
        for offset in range(0, len(raw), 37):
            capture.reducer.feed(raw[offset:offset + 37])
    return SimpleNamespace(root=root, attachment=attachment, browser=browser, result=result, report=report, capture=capture)


def test_exact_chain_survives_only_as_safe_metadata(evidence):
    result = evidence.capture.summarize(evidence.report, evidence.root)
    assert result["status"] == "complete"
    assert {key: result[key] for key in PROVENANCE} == PROVENANCE
    attempt = result["attempts"][0]
    assert (attempt["chat_id"], attempt["message_id"], attempt["task_id"]) == (CHAT, MESSAGE, TASK)
    assert attempt["api_marker"] == attempt["worker_context"] == "observed"
    assert [event["event"] for event in attempt["events"]] == ["api_marker_applied", "api_dispatch", "worker_mock", "preprocessing", "worker_exception"]
    assert attempt["events"][-1]["exception_class"] == "MockCacheMiss"
    assert attempt["events"][-1]["frame"] == {"file": "backend/apps/ai/tasks/ask_skill_task.py", "line": 3370, "function": "preprocess"}
    serialized = json.dumps(result)
    for forbidden in (SECRET, "secret.invalid", "headers", "cookie", "user_id", "exception_msg", "LIVE MOCK"):
        assert forbidden not in serialized


@pytest.mark.parametrize("fault", ["duplicate", "escape", "symlink", "parent_symlink", "fifo", "oversize", "wrong_group", "wrong_retry", "extra_private", "wrong_message", "wrong_chat", "window", "incoming_private"])
def test_untrusted_attachments_fail_closed(evidence, fault, tmp_path):
    result, browser, path = evidence.result, evidence.browser, evidence.attachment
    if fault == "duplicate":
        result["attachments"] *= 2
    elif fault == "escape":
        outside = tmp_path / "outside.json"
        outside.write_text(SECRET)
        result["attachments"][0]["path"] = str(outside)
    elif fault in {"symlink", "parent_symlink"}:
        path.unlink()
        if fault == "symlink":
            path.symlink_to(tmp_path / "private")
        else:
            path.parent.rmdir()
            path.parent.symlink_to(tmp_path, target_is_directory=True)
    elif fault == "fifo":
        import os
        path.unlink()
        os.mkfifo(path)
    elif fault == "oversize":
        path.write_text(SECRET * diagnostic.MAX_BROWSER)
    elif fault == "wrong_group":
        browser["group"] = SECRET
    elif fault == "wrong_retry":
        browser["retry"] = 1
    elif fault == "extra_private":
        browser["headers"] = SECRET
    elif fault == "wrong_message":
        browser["events"][1]["message_id"] = OTHER
    elif fault == "wrong_chat":
        browser["events"][0]["chat_id"] = OTHER
    elif fault == "window":
        browser["events"][0]["utc"] = "2026-10-23T00:10:00Z"
    elif fault == "incoming_private":
        browser["events"][1]["marker_present"] = SECRET
    if fault in {"wrong_group", "wrong_retry", "extra_private", "wrong_message", "wrong_chat", "window", "incoming_private"}:
        path.write_text(json.dumps(browser))
    output = evidence.capture.summarize(evidence.report, evidence.root)
    assert output["status"] == "incomplete"
    assert SECRET not in json.dumps(output)
    assert not output["attempts"][0].get("events")


def test_other_chat_or_ambiguous_task_is_not_attributed(evidence):
    raw = line("api", diagnostic.API_LOGGER, f"[PERF] In-process ai.ask dispatch took 0.1s, Task ID: {OTHER} for user_id={SECRET}, chat_id={CHAT}, message_id={MESSAGE}")
    evidence.capture.reducer.feed(raw)
    result = evidence.capture.summarize(evidence.report, evidence.root)
    assert result["status"] == "incomplete"
    assert not result["attempts"][0].get("task_id")


def test_validated_browser_task_retains_worker_evidence_without_inventing_dispatch(evidence):
    evidence.capture.reducer.events = [event for event in evidence.capture.reducer.events if event["event"] != "api_dispatch"]
    attempt = evidence.capture.summarize(evidence.report, evidence.root)["attempts"][0]
    assert attempt["status"] == "incomplete" and attempt["task_id"] == TASK
    assert attempt["task_origin"] == "browser_announcement"
    assert "dispatch_not_observed" in attempt["reasons"]
    assert attempt["worker_context"] == "observed"


def test_missing_transport_marker_is_not_called_a_complete_chain(evidence):
    evidence.browser["events"][0].update(marker_present=False, expected_group_match=False)
    evidence.attachment.write_text(json.dumps(evidence.browser))
    attempt = evidence.capture.summarize(evidence.report, evidence.root)["attempts"][0]
    assert attempt["status"] == "incomplete" and "browser_marker_not_observed" in attempt["reasons"]


@pytest.mark.parametrize("fault", ["duration_bool", "duration_large", "offset", "duplicate_retry", "wrong_file", "depth", "coverage", "provenance"])
def test_report_and_lineage_bounds(evidence, fault):
    if fault == "duration_bool":
        evidence.result["duration"] = True
    elif fault == "duration_large":
        evidence.result["duration"] = 600001
    elif fault == "offset":
        evidence.result["startTime"] = "2026-10-23T00:00:10+01:00"
    elif fault == "duplicate_retry":
        spec = evidence.report["suites"][0]["suites"][0]["specs"][0]
        spec["tests"][0]["results"] *= 2
    elif fault == "wrong_file":
        evidence.report["suites"][0]["suites"][0]["specs"][0]["file"] = "other.spec.ts"
    elif fault == "depth":
        for _ in range(8):
            evidence.report = {"suites": [evidence.report]}
    elif fault == "coverage":
        evidence.capture.ended = "2026-10-23T00:00:11Z"
    else:
        evidence.capture.provenance["harness_commit"] = SECRET
    output = evidence.capture.summarize(evidence.report, evidence.root)
    assert output["status"] == "incomplete"
    assert SECRET not in json.dumps(output)


def test_failed_first_attempt_is_retained_without_changing_report(evidence):
    test = evidence.report["suites"][0]["suites"][0]["specs"][0]["tests"][0]
    test["results"].append({"status": "passed", "retry": 1})
    original = json.dumps(evidence.report)
    assert evidence.capture.summarize(evidence.report, evidence.root)["status"] == "complete"
    assert json.dumps(evidence.report) == original
    test["results"] = [{"status": "passed"}]
    assert evidence.capture.summarize(evidence.report, evidence.root)["status"] == "not_needed"


def test_chunk_line_limit_does_not_spool_or_overwrite_early_events(evidence, monkeypatch):
    early = list(evidence.capture.reducer.events)
    for _ in range(9):
        evidence.capture.reducer.feed(b"x" * 8192)
    evidence.capture.reducer.feed(b"\n")
    monkeypatch.setattr(diagnostic, "MAX_EVENTS", len(early))
    evidence.capture.reducer.feed(line("ai-worker", diagnostic.ASK_LOGGER, f"[Task ID: {TASK}] Starting main processing step...", 15))
    assert evidence.capture.reducer.events == early
    assert evidence.capture.reducer.flags == {"line_limit", "event_limit"}
    assert len(evidence.capture.reducer.buffer) <= diagnostic.MAX_LINE
    assert evidence.capture.summarize(evidence.report, evidence.root)["attempts"][0]["api_marker"] == "observed"


@pytest.mark.parametrize("limit", ["memory", "context", "output"])
def test_hard_memory_context_and_output_limits(evidence, monkeypatch, limit):
    if limit == "memory":
        monkeypatch.setattr(diagnostic, "MAX_STORE", evidence.capture.reducer.bytes)
    elif limit == "context":
        monkeypatch.setattr(diagnostic, "MAX_CONTEXTS", len(evidence.capture.reducer.contexts))
    else:
        monkeypatch.setattr(diagnostic, "MAX_OUTPUT", 1000)
    evidence.capture.reducer.feed(line("ai-worker", diagnostic.ASK_LOGGER, f"[Task ID: {OTHER}] Starting main processing step...", 15))
    result = evidence.capture.summarize(evidence.report, evidence.root)
    assert result["status"] == "incomplete"
    assert len(diagnostic.encoded(result)) <= diagnostic.MAX_OUTPUT
    assert evidence.capture.reducer.bytes <= diagnostic.MAX_STORE


class Pipe:
    def __init__(self):
        self.closed = threading.Event()

    def read1(self, _count):
        self.closed.wait(2)
        return b""

    def close(self):
        self.closed.set()


class Process:
    def __init__(self, ignore_terminate=False):
        self.stdout = Pipe()
        self.calls = []
        self.ignore_terminate = ignore_terminate

    def poll(self):
        return 0 if self.stdout.closed.is_set() else None

    def terminate(self):
        self.calls.append("terminate")
        if not self.ignore_terminate:
            self.stdout.close()

    def kill(self):
        self.calls.append("kill")
        self.stdout.close()

    def wait(self, timeout):
        self.calls.append("wait")
        if not self.stdout.closed.is_set():
            raise subprocess.TimeoutExpired("private command", timeout)
        return 0


@pytest.fixture
def controller(tmp_path, monkeypatch):
    (tmp_path / "test-results").mkdir()
    process = Process()
    calls, timers = [], []

    class Timer:
        def __init__(self, seconds, callback):
            assert seconds == 1210
            self.callback = callback
            timers.append(self)

        def start(self): pass
        def cancel(self): pass

    fake_environment = SimpleNamespace(SOURCE=str(tmp_path), COMPOSE_PATH=tmp_path / "test-results/ci-private/compose.json", require_runner=lambda: None)
    monkeypatch.setitem(sys.modules, "ci_environment", fake_environment)
    monkeypatch.setenv("CI_TEST_MODE", "e2e")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    monkeypatch.setenv("CI_HARNESS_COMMIT", "b" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(diagnostic.subprocess, "check_output", lambda *a, **k: "a" * 40)
    monkeypatch.setattr(diagnostic.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)) or process)
    monkeypatch.setattr(diagnostic.threading, "Timer", Timer)
    return SimpleNamespace(root=tmp_path, process=process, calls=calls, timers=timers, environment=fake_environment)


@pytest.mark.parametrize("failure", [False, True])
def test_controller_stops_reaps_and_preserves_original_exception(controller, failure):
    original = RuntimeError(SECRET)
    controller.process.ignore_terminate = True
    try:
        with diagnostic.capture_scope(diagnostic.SPEC, controller.root, 0, enabled=True) as capture:
            assert not capture.reducer.flags
            if failure:
                raise original
    except RuntimeError as error:
        assert failure and error is original
    assert controller.process.calls == ["terminate", "wait", "kill", "wait"]
    assert not capture.reader.is_alive()
    command, kwargs = controller.calls[0]
    assert command[:4] == ["docker", "compose", "-f", str(controller.environment.COMPOSE_PATH)]
    assert command[4:9] == ["logs", "--follow", "--no-color", "--timestamps", "--since"]
    assert command[-2:] == ["api", "ai-worker"]
    assert kwargs["stderr"] == subprocess.DEVNULL and "shell" not in kwargs
    if failure:
        receipt = json.loads((controller.root / "test-results/ci-spec-0-web-search-diagnostics.json").read_text())
        assert receipt["status"] == "incomplete"
        assert SECRET not in json.dumps(receipt)


def test_watchdog_kills_at_deadline_and_scope_is_fail_closed(controller, monkeypatch):
    for name, enabled, mode in [("other.spec.ts", True, "e2e"), (diagnostic.SPEC, False, "e2e"), (diagnostic.SPEC, True, "component")]:
        monkeypatch.setenv("CI_TEST_MODE", mode)
        assert diagnostic.start_capture(name, controller.root, enabled=enabled) is None
    assert controller.calls == []
    monkeypatch.setenv("CI_TEST_MODE", "e2e")
    capture = diagnostic.start_capture(diagnostic.SPEC, controller.root, enabled=True)
    controller.timers[0].callback()
    assert controller.process.calls == ["kill", "wait"]
    assert "time_limit" in capture.reducer.flags and not capture.reader.is_alive()


def test_reap_error_is_bounded_and_does_not_replace_original_failure(controller, monkeypatch):
    original_wait = controller.process.wait
    count = 0

    def wait(timeout):
        nonlocal count
        count += 1
        if count == 1:
            raise OSError(SECRET)
        return original_wait(timeout)

    monkeypatch.setattr(controller.process, "wait", wait)
    original = RuntimeError(SECRET)
    with pytest.raises(RuntimeError) as caught:
        with diagnostic.capture_scope(diagnostic.SPEC, controller.root, 1, enabled=True) as capture:
            raise original
    assert caught.value is original and count == 2
    assert "kill" in controller.process.calls and "capture_stop_failed" in capture.reducer.flags
    assert not capture.reader.is_alive()


def test_guard_or_follower_start_failure_cannot_leak_exception(controller, monkeypatch):
    def fail(): raise RuntimeError(SECRET)
    controller.environment.require_runner = fail
    capture = diagnostic.start_capture(diagnostic.SPEC, controller.root, enabled=True)
    assert controller.calls == []
    assert capture.summarize({}, controller.root)["status"] == "incomplete"
    assert SECRET not in json.dumps(capture.summarize({}, controller.root))
    controller.environment.require_runner = lambda: None
    monkeypatch.setattr(diagnostic.subprocess, "Popen", lambda *a, **k: fail())
    capture = diagnostic.start_capture(diagnostic.SPEC, controller.root, enabled=True)
    assert capture.reducer.flags == {"capture_start_failed"}


def test_wrong_logger_or_uncorrelated_replay_and_private_text_are_discarded():
    reducer = diagnostic.Reducer()
    for logger, message in [("untrusted.logger", f"[Task ID: {TASK}] Starting main processing step..."),
                            (diagnostic.ASK_LOGGER, f"User said [Task ID: {TASK}] LIVE MOCK: group='web_search_web'"),
                            ("backend.shared.testing.api_response_cache", f"[LiveMock] Cache HIT: llm/{SECRET} (group=web_search_web)")]:
        reducer.feed(line("ai-worker", logger, message))
    assert reducer.events == []


def test_json_complexity_is_bounded_before_ignored_fields_allocate(monkeypatch):
    raw = line("ai-worker", diagnostic.ASK_LOGGER, f"[Task ID: {TASK}] Starting main processing step...", ignored=[{}] * 10000)
    monkeypatch.setattr(diagnostic.json, "loads", lambda _: pytest.fail("decoder must not allocate the hostile structure"))
    reducer = diagnostic.Reducer()
    reducer.feed(raw)
    assert reducer.events == []
    assert reducer.flags == {"json_structure_limit"}


def test_report_queue_is_bounded_before_children_are_materialized(evidence):
    class Children(list):
        traversed = False

        def __iter__(self):
            self.traversed = True
            return super().__iter__()

    children = Children([{}] * 1000)
    result = evidence.capture.summarize({"suites": children}, evidence.root)
    assert result["status"] == "incomplete" and not children.traversed
