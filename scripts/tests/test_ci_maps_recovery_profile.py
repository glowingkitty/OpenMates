# contract-test-file: tooling
"""Keep marker-only chat epoch activation inside its disposable marker-only CI stack."""

import contextlib
import io
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import ci_environment


AUTHORED_CASE_TITLE = "saved authored results preserve all admitted typed records through fresh CLI reads"


def test_failed_authored_case_extracts_listener_cause_before_private_byte_cap(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    target = json.dumps({
        "name": "backend.core.api.app.routes.websockets", "level": "ERROR",
        "message": "AI Stream Listener: Error processing message: private-diagnostic-sentinel",
        "exc_info": 'Traceback (most recent call last):\n'
                    '  File "/app/backend/core/api/app/routes/websockets.py", line 1579, in listen_for_ai_chat_streams\n'
                    '  File "/app/backend/core/api/app/routes/handlers/websocket_handlers/chat_recovery_job_handlers.py", line 590, in send_available_recovery_outputs\n'
                    'ValueError: private-query-and-owner-11111111-1111-4111-8111-111111111111',
        "private_unknown_field": "private-raw-body",
    })
    noise = json.dumps({
        "name": "backend.core.api.app.services.openobserve_push_service", "level": "ERROR",
        "message": "private-unrelated-exporter-error",
        "exc_info": 'Traceback (most recent call last):\n'
                    '  File "/usr/local/lib/python3.13/site-packages/aiohttp/connector.py", line 1598, in _create_direct_connection\n'
                    'ClientConnectorDNSError: private-hostname',
    })
    # The target is within the 8,000-line window but deliberately outside its
    # 800 KB raw retention cap, followed by unrelated structured DNS noise.
    output = "outside-line-window\napi-1 | " + target + "\n" + "\n".join(["api-1 | " + noise] * 7999)
    calls = []

    def compose(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(runner, "compose", compose)
    failed = {"status": "timedOut", "startTime": "2026-10-26T11:45:00Z", "duration": 120_000}
    report = {"suites": [{"specs": [{"title": AUTHORED_CASE_TITLE,
                                    "tests": [{"results": [failed, {**failed, "status": "passed"}]}]}]}]}
    summaries = runner.capture_recovery_receipt_api_diagnostics(report, 2)
    assert summaries == [{"exception_class": "ValueError", "function": "send_available_recovery_outputs", "line": 590,
                          "final_delivery_stages": [], "final_delivery_truncated": False,
                          "fixture_final_publications": [], "fixture_publication_truncated": False}]
    assert calls == [(("logs", "--no-color", "--since", "2026-10-26T11:44:58+00:00",
                       "--until", "2026-10-26T11:47:05+00:00", "--tail", "8000", "api"),
                      {"capture": True, "timeout": 90}),
                     (("logs", "--no-color", "--since", "2026-10-26T11:44:58+00:00",
                       "--until", "2026-10-26T11:47:05+00:00", "--tail", "2000", "ai-worker"),
                      {"capture": True, "timeout": 90})]
    private = tmp_path / "ci-private"
    retained = private / "recovery-api-spec-2-result-0.log"
    raw = retained.read_bytes()
    assert len(raw) <= 800_000 and len(raw.splitlines()) <= 8000
    assert b"private-diagnostic-sentinel" not in raw and b"outside-line-window" not in raw
    assert b"private-unrelated-exporter-error" in raw
    assert retained.stat().st_mode & 0o777 == 0o600
    assert private.stat().st_mode & 0o777 == 0o700
    public = json.dumps(summaries)
    assert "private-" not in public and "11111111-1111-4111-8111-111111111111" not in public
    assert "connector" not in public


def test_authored_delivery_stages_and_protocol_warnings_need_no_traceback(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    websocket_logger = "backend.core.api.app.routes.websockets"
    messages = [
        (websocket_logger, "Final stream delivery stage=final_received device=0 success=none exception=none code=none"),
        (websocket_logger, "Final stream delivery stage=outputs_result device=1 success=false exception=ChatRecoveryProtocolError code=forbidden"),
        (websocket_logger, "Final stream delivery stage=outputs_result device=2 success=false exception=ReadTimeout code=none"),
        (websocket_logger, "Final stream delivery stage=final_send device=2 success=true exception=private_sentinel code=private_sentinel"),
        (websocket_logger, "Final stream delivery stage=private_sentinel device=1 success=true exception=none code=none"),
        (websocket_logger, "Final stream delivery stage=final_send device=129 success=true exception=none code=none"),
        ("private_logger", "Final stream delivery stage=final_send device=2 success=true exception=none code=none"),
        ("backend.core.api.app.services.chat_recovery_service",
         "Chat recovery transaction rejected: operation=list_pending_outputs code=chat_not_found status=404"),
        ("backend.core.api.app.services.chat_recovery_service",
         "Chat recovery transaction rejected: operation=list_available_jobs code=private_sentinel status=500"),
        ("backend.core.api.app.services.chat_recovery_service",
         "Chat recovery transaction rejected: operation=private_sentinel code=chat_not_found status=404"),
    ]
    output = "\n".join("api-1 | " + json.dumps({"name": name, "message": message,
        "private_unknown_field": "private_sentinel"}) for name, message in messages)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(stdout=output))
    report = {"suites": [{"specs": [{"title": AUTHORED_CASE_TITLE, "tests": [{"results": [
        {"status": "failed", "startTime": "2026-10-26T11:45:00Z", "duration": 120_000},
    ]}]}]}]}
    summaries = runner.capture_recovery_receipt_api_diagnostics(report, 0)
    assert summaries == [{"exception_class": "none", "function": "none", "line": 0,
        "final_delivery_stages": [
            {"stage": "final_received", "device": 0, "success": None, "exception_class": "none", "code": "none"},
            {"stage": "outputs_result", "device": 1, "success": False, "exception_class": "ChatRecoveryProtocolError", "code": "forbidden"},
            {"stage": "outputs_result", "device": 2, "success": False, "exception_class": "ReadTimeout", "code": "none"},
            {"stage": "final_send", "device": 2, "success": True, "exception_class": "other", "code": "other"},
        ], "final_delivery_truncated": False,
        "fixture_final_publications": [], "fixture_publication_truncated": False,
        "recovery_protocol_rejections": [
            {"operation": "list_pending_outputs", "code": "chat_not_found", "status": 404},
            {"operation": "list_available_jobs", "code": "other", "status": 500},
        ]}]
    assert "private_sentinel" not in json.dumps(summaries)
    assert "private_logger" not in json.dumps(summaries)


def test_authored_delivery_diagnostics_bound_exported_event_counts(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    stage = json.dumps({"name": "backend.core.api.app.routes.websockets",
        "message": "Final stream delivery stage=jobs_begin device=1 success=none exception=none code=none"})
    rejection = json.dumps({"name": "backend.core.api.app.services.chat_recovery_service",
        "message": "Chat recovery transaction rejected: operation=list_available_jobs code=transaction_failed status=500"})
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(stdout="\n".join([stage] * 65 + [rejection] * 17)))
    report = {"suites": [{"specs": [{"title": AUTHORED_CASE_TITLE, "tests": [{"results": [
        {"status": "failed", "startTime": "2026-10-26T11:45:00Z", "duration": 120_000},
    ]}]}]}]}
    summary = runner.capture_recovery_receipt_api_diagnostics(report, 0)[0]
    assert len(summary["final_delivery_stages"]) == 64
    assert summary["final_delivery_truncated"] is True
    assert len(summary["recovery_protocol_rejections"]) == 16


def test_fixture_publication_summary_exports_only_fixed_facts(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    def row(message, name="backend.apps.ai.testing.mock_replay"):
        return json.dumps({"name": name, "message": message, "content": "private_canary"})

    output = "\n".join([
        row("Fixture final publication stage=begin success=none"),
        row("Fixture final publication stage=complete success=false"),
        row("Fixture final publication stage=complete success=true"),
        row("Fixture final publication stage=private_canary success=true"),
        row("Fixture final publication stage=complete success=private_canary"),
        row("Fixture final publication stage=begin success=true"),
        row("Fixture final publication stage=complete success=none"),
        row("Fixture final publication stage=complete success=true", "private_canary"),
    ])
    events, truncated = runner._fixture_final_publication_summary(output)
    assert events == [{"stage": "begin", "success": None},
                      {"stage": "complete", "success": False}, {"stage": "complete", "success": True}]
    assert truncated is False
    assert "private_canary" not in json.dumps(events)
    events, truncated = runner._fixture_final_publication_summary("\n".join([row("Fixture final publication stage=begin success=none")] * 9))
    assert len(events) == 8 and truncated is True


@pytest.mark.parametrize("custom_error", [False, True])
def test_fixture_publication_log_failure_preserves_api_summary(tmp_path, monkeypatch, custom_error):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    def compose(*args, **kwargs):
        if args[-1] == "ai-worker":
            error_class = type("private_canary", (RuntimeError,), {}) if custom_error else RuntimeError
            raise error_class("private_canary")
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(runner, "compose", compose)
    report = {"suites": [{"specs": [{"title": AUTHORED_CASE_TITLE, "tests": [{"results": [
        {"status": "failed", "startTime": "2026-10-26T11:45:00Z", "duration": 120_000},
    ]}]}]}]}
    summary = runner.capture_recovery_receipt_api_diagnostics(report, 0)[0]
    assert summary["final_delivery_stages"] == []
    assert summary["fixture_final_publications"] == []
    assert summary["fixture_publication_capture_error"] == ("other" if custom_error else "RuntimeError")
    assert "private_canary" not in json.dumps(summary)
    assert len(list((tmp_path / "ci-private").iterdir())) == 1


@pytest.mark.parametrize("title", [
    AUTHORED_CASE_TITLE + " ", AUTHORED_CASE_TITLE + " extended", "prefix " + AUTHORED_CASE_TITLE,
    AUTHORED_CASE_TITLE.upper(), "unrelated failed case",
])
def test_authored_diagnostics_reject_near_names_and_unrelated_cases(tmp_path, monkeypatch, title):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Unadmitted case reached Docker"))
    report = {"suites": [{"specs": [{"title": title, "tests": [{"results": [
        {"status": "failed", "startTime": "2026-10-26T11:45:00Z", "duration": 120_000},
    ]}]}]}]}
    assert runner.capture_recovery_receipt_api_diagnostics(report, 0) == []
    assert list((tmp_path / "ci-private").iterdir()) == []


@pytest.mark.parametrize("start,duration", [
    ("2026-10-26T11:45:00", 120_000), ("2026-10-26T12:45:00+01:00", 120_000),
    ("2026-10-26T11:45:00Z", 600_001), ("2026-10-26T11:45:00Z", True),
])
def test_authored_diagnostics_reject_unbounded_or_non_utc_windows(tmp_path, monkeypatch, start, duration):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Invalid window reached Docker"))
    report = {"suites": [{"specs": [{"title": AUTHORED_CASE_TITLE, "tests": [{"results": [
        {"status": "failed", "startTime": start, "duration": duration},
    ]}]}]}]}
    assert runner.capture_recovery_receipt_api_diagnostics(report, 0) == [
        {"exception_class": "ValueError", "function": "none", "line": 0},
    ]


def test_authored_diagnostics_retain_at_most_four_failed_attempts(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    calls = []

    def compose(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="bounded-private-log")

    monkeypatch.setattr(runner, "compose", compose)
    failed = {"status": "failed", "startTime": "2026-10-26T11:45:00Z", "duration": 120_000}
    report = {"suites": [{"specs": [{"title": AUTHORED_CASE_TITLE,
                                    "tests": [{"results": [failed] * 5}]}]}]}
    assert len(runner.capture_recovery_receipt_api_diagnostics(report, 0)) == 4
    assert len(calls) == 8
    assert len(list((tmp_path / "ci-private").iterdir())) == 4


def test_failed_native_cache_retains_only_bounded_private_api_window(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    calls = []

    def compose(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="private-native-diagnostic-sentinel")

    monkeypatch.setattr(runner, "compose", compose)
    failure = {"status": "failed", "startTime": "2026-10-08T13:00:00Z", "duration": 1000}
    report = {"suites": [{"specs": [
        {"title": "native cache keeps selected math tools and settled billing across five chat turns",
         "tests": [{"results": [failure, {**failure, "status": "passed"}]}]},
        {"title": "unrelated failed case", "tests": [{"results": [failure]}]},
    ]}]}

    summaries = runner.capture_recovery_receipt_api_diagnostics(report, 0)
    assert summaries == [{"exception_class": "none", "function": "none", "line": 0}]
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("logs", "--no-color", "--since", "2026-10-08T12:59:58+00:00",
                    "--until", "2026-10-08T13:00:06+00:00", "--tail", "2000", "api")
    assert kwargs == {"capture": True, "timeout": 90}
    retained = tmp_path / "ci-private" / "recovery-api-spec-0-result-0.log"
    assert retained.read_text() == "private-native-diagnostic-sentinel"
    assert retained.stat().st_mode & 0o777 == 0o600
    assert "private-native-diagnostic-sentinel" not in json.dumps(summaries)


@pytest.mark.parametrize("log_text,expected", [
    ("CACHE_OP_ERROR: Failed to save vault-encrypted message to AI cache.\n"
     "Failed to save message private-message to cache or update versions for chat private-chat.",
     {"cache_failure_stages": ["current_message_save_failure", "ai_history_append_failure"]}),
    ("Failed to replace AI history for chat 11111111-1111-1111-1111-111111111111: RuntimeError",
     {"exception_class": "RuntimeError",
      "cache_failure_stages": ["client_history_recache_failure"],
      "cache_recache_exception_class": "RuntimeError"}),
    ("Failed to replace AI history for chat [REDACTED_ID]: RuntimeError; operation=prior_row_append",
     {"exception_class": "RuntimeError",
      "cache_failure_stages": ["client_history_recache_failure"],
      "cache_recache_exception_class": "RuntimeError",
      "cache_recache_operation": "prior_row_append"}),
    ("Failed to replace AI history for chat private-chat: ValueError; operation=private-content",
     {"exception_class": "ValueError",
      "cache_failure_stages": ["client_history_recache_failure"],
      "cache_recache_exception_class": "ValueError"}),
    ("CACHE_OP_ERROR: Failed to set explicit messages_v to private-version.\n"
     "CACHE_OP_ERROR: Failed to update last_edited_overall_timestamp for user private-user.",
     {"cache_failure_stages": ["messages_version_failure", "chat_score_failure"]}),
    ("An unrelated warning with private-user and private-message", {}),
])
def test_private_cache_failures_deliver_only_fixed_stage_and_type(tmp_path, monkeypatch, log_text, expected):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(stdout=log_text))
    report = {"suites": [{"specs": [{
        "title": "native cache keeps selected math tools and settled billing across five chat turns",
        "tests": [{"results": [{"status": "failed", "startTime": "2026-10-08T13:00:00Z", "duration": 1000}]}],
    }]}]}

    summaries = runner.capture_recovery_receipt_api_diagnostics(report, 0)
    assert summaries == [{"exception_class": "none", "function": "none", "line": 0, **expected}]
    public = json.dumps(summaries)
    assert "private-" not in public
    assert "11111111-1111-1111-1111-111111111111" not in public
    retained = tmp_path / "ci-private" / "recovery-api-spec-0-result-0.log"
    assert retained.read_text() == log_text
    assert retained.stat().st_mode & 0o777 == 0o600


def _runner_profile(tmp_path, monkeypatch, **options):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    profile = ci_environment.compose_profile("a" * 40, **options)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    return runner, profile, compose_path


@pytest.mark.parametrize("initial,pending", [
    ({"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}, False),
    ({"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}, False),
    ({"protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0}, False),
    ({"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 1}, False),
    ({"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}, True),
])
@pytest.mark.parametrize("spec_name", [
    "cli-authored-results.spec.ts",
    "stop-new-chat-draft.spec.ts",
    "cli-rust-core-essential.spec.ts",
    "rust-core-browser-session.spec.ts",
    "rust-core-browser-password-entry.spec.ts",
    "maps-discovery-chat.spec.ts",
    "audio-recording-deferred-send.spec.ts",
    "workflow-metadata-warmup.spec.ts",
    "connection-resilience.spec.ts",
    "chat-saved-followup-admission.spec.ts",
    "skill-web-search.spec.ts",
    "native-cache-selected-tools.spec.ts",
])
def test_marker_chat_epoch_activates_only_fresh_idle_state(tmp_path, monkeypatch, initial, pending, spec_name):
    runner, profile, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    state = initial.copy()
    calls = []

    class Cache:
        async def close(self):
            pass

    class Directus:
        def __init__(self, cache_service):
            pass

        async def close(self):
            pass

    class Recovery:
        def __init__(self, directus):
            pass

        async def execute(self, operation, body):
            calls.append(operation)
            if operation == "get_cutover_state":
                return state.copy()
            if operation == "set_sends_paused":
                state["sends_paused"] = body["sends_paused"]
                return state.copy()
            if operation == "activate_protocol_epoch":
                assert state == {"protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0}
                if pending:
                    raise RuntimeError("legacy_batches_pending")
                state["protocol_epoch"] = 1
                return {**state, "activated": True}
            raise AssertionError(operation)

    class Controller:
        def __init__(self, cache, directus):
            pass

        async def get_state(self, **kwargs):
            return state.copy()

    modules = {
        "backend.core.api.app.services.chat_recovery_service": ("ChatRecoveryService", Recovery),
        "backend.core.api.app.services.chat_recovery_cutover": ("ChatRecoveryCutoverController", Controller),
        "backend.core.api.app.services.cache": ("CacheService", Cache),
        "backend.core.api.app.services.directus": ("DirectusService", Directus),
    }
    for name, (attribute, cls) in modules.items():
        module = ModuleType(name)
        setattr(module, attribute, cls)
        monkeypatch.setitem(sys.modules, name, module)
    for key, value in profile["services"]["api"]["environment"].items():
        if isinstance(value, str):
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE", "1")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)

    def compose(*args, **kwargs):
        assert args[:6] == ("exec", "-T", "-e", "OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE=1", "api", "python")
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                exec(args[-1], {"__name__": "__main__"})
        except RuntimeError as exc:
            raise subprocess.CalledProcessError(1, args, stderr=str(exc)) from exc
        return SimpleNamespace(stdout=output.getvalue())

    monkeypatch.setattr(runner, "compose", compose)
    if initial == {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0} and not pending:
        assert runner.activate_isolated_marker_chat_epoch(spec_name) == {
            "protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0,
        }
        assert calls == ["get_cutover_state", "set_sends_paused", "activate_protocol_epoch",
                         "set_sends_paused"]
    else:
        with pytest.raises(RuntimeError, match="activation failed"):
            runner.activate_isolated_marker_chat_epoch(spec_name)
        if pending:
            assert calls == ["get_cutover_state", "set_sends_paused", "activate_protocol_epoch",
                             "set_sends_paused"]
            assert state["sends_paused"] is False
        else:
            assert calls == ["get_cutover_state"]


@pytest.mark.parametrize("profile_options,mutation", [
    ({}, None),
    ({"ai_fixtures": True}, lambda p: p["services"]["api"]["environment"].pop("OPENMATES_CI_AI_FIXTURES")),
    ({"ai_fixtures": True}, lambda p: p["services"]["api"]["environment"].update(OPENMATES_CI_ISOLATED="0")),
    ({"ai_fixtures": True}, lambda p: p["networks"]["default"].update(internal=False)),
    ({"public_provider": True}, None),
    ({"storage_capacity": True}, None),
])
@pytest.mark.parametrize("spec_name", ["maps-discovery-chat.spec.ts", "cli-rust-core-essential.spec.ts", "rust-core-browser-session.spec.ts", "rust-core-browser-password-entry.spec.ts"])
def test_maps_epoch_rejects_other_profiles(tmp_path, monkeypatch, profile_options, mutation, spec_name):
    runner, profile, path = _runner_profile(tmp_path, monkeypatch, **profile_options)
    if mutation:
        mutation(profile)
        path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="isolated marker-only AI profile"):
        runner.activate_isolated_marker_chat_epoch(spec_name)


def test_maps_epoch_rejects_other_spec_and_bad_receipt(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="exact browser spec"):
        runner.activate_isolated_marker_chat_epoch("storage-capacity-replay.spec.ts")
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(
        stdout='{"protocol_epoch": 1, "sends_paused": true, "legacy_in_flight": 0}\n'))
    with pytest.raises(RuntimeError, match="incomplete"):
        runner.activate_isolated_marker_chat_epoch("maps-discovery-chat.spec.ts")


def test_maps_epoch_requires_github_runner(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "require_runner", ci_environment.require_runner)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="GitHub-hosted"):
        runner.activate_isolated_marker_chat_epoch("maps-discovery-chat.spec.ts")


def test_capacity_epoch_profile_guard_remains_separate(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="exact isolated capacity profile"):
        runner.activate_isolated_recovery_epoch()


@pytest.mark.parametrize("specs", [
    ["cli-authored-results.spec.ts"],
    ["stop-new-chat-draft.spec.ts"],
    ["skill-web-search.spec.ts", "connection-resilience.spec.ts"],
    ["cli-rust-core-essential.spec.ts"],
    ["cli-rust-core-essential.spec.ts", "connection-resilience.spec.ts"],
])
def test_send_and_reconnect_batch_activates_epoch_once_before_browser(tmp_path, monkeypatch, specs):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    for spec in specs:
        (web / "tests" / spec).write_text("// authenticated marker fixture")
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(runner, "WEB", web)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    cli = web / "node_modules/@playwright/test/cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("// inert Playwright entry; process execution is stubbed")
    monkeypatch.setattr(runner, "pinned_node", lambda: "/synthetic/pinned-node")
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "reserved_account_slot", lambda _: 1)
    monkeypatch.setattr(runner, "provision_account", lambda _, identity_index: {
        "OPENMATES_TEST_ACCOUNT_EMAIL": f"fixture-{identity_index}@example.com",
    })
    calls = []
    diagnostic_calls = []
    monkeypatch.setattr(runner, "capture_recovery_receipt_api_diagnostics",
                        lambda report, index: diagnostic_calls.append(index) or [])
    receipt = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}

    def activate(spec):
        calls.append(("activate", spec))
        return receipt

    monkeypatch.setattr(runner, "activate_isolated_marker_chat_epoch", activate)
    monkeypatch.setattr(runner, "activate_isolated_recovery_epoch", lambda: pytest.fail("Capacity activation reached"))

    class Process:
        def terminate(self):
            pass

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(runner, "wait_web", lambda _: None)

    def browser(command, **kwargs):
        assert command[:3] == ["/synthetic/pinned-node", str(cli), "test"]
        calls.append(("browser", command[3]))
        assert calls[0] == ("activate", specs[0])
        from pathlib import Path
        Path(kwargs["env"]["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(
            json.dumps({"stats": {"expected": 1}})
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", browser)
    outcomes = runner.run_e2e(specs)
    assert calls == [("activate", specs[0]), *(('browser', 'tests/' + spec) for spec in specs)]
    assert all(result["exit_code"] == 0 for result in outcomes)
    assert all(result["accounts"]["recovery_protocol_epoch"] == 1 for result in outcomes)
    assert diagnostic_calls == ([0] if specs == ["cli-authored-results.spec.ts"] else [])


@pytest.mark.parametrize("spec_name", [
    "nested/cli-rust-core-essential.spec.ts", "cli-rust-core-essential.spec.ts.backup",
    "cli-rust-core-essential-other.spec.ts", "cli-rust-tui-proof.spec.ts",
])
def test_essential_epoch_selector_does_not_admit_near_names(tmp_path, monkeypatch, spec_name):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="exact browser spec"):
        runner.activate_isolated_marker_chat_epoch(spec_name)
