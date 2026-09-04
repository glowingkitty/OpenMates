#!/usr/bin/env python3
# contract-test-file: tooling
"""
Regression tests for nightly Discord test summaries.

The summary must show where failures are concentrated before listing the
affected test files. Error causes and stack traces remain in the full reports
rather than being posted in the channel.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests_discord", RUN_TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scheduled_publication_maintenance_scans_root_and_session_worktrees(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    (tmp_path / "test-results/spec-demos").mkdir(parents=True)
    (tmp_path / ".openmates-agent-worktrees/agent-one/test-results/spec-demos").mkdir(parents=True)
    seen = []
    monkeypatch.setattr(run_tests, "CONTROL_PLANE_ROOT", tmp_path)
    monkeypatch.setattr(
        run_tests,
        "_sweep_spec_demo_publications",
        lambda root, **_kwargs: seen.append(root)
        or {"scanned": 1, "retried": 1, "delivered": 1, "expired_deleted": 0},
    )

    result = run_tests._maintain_spec_demo_publications()

    assert len(seen) == 2
    assert result == {"scanned": 2, "retried": 2, "delivered": 2, "expired_deleted": 0}


def test_discord_failure_embeds_group_files_by_suite_and_product_area():
    run_tests = load_run_tests_module()
    suites = {
        "pytest_unit": {
            "tests": [
                {
                    "name": "tests/test_settings_account_delete_force_logout.py::test_delete_account",
                    "status": "failed",
                    "error": "KeyError: private implementation detail",
                },
                {
                    "name": "tests/test_billing_routes.py::test_invoice",
                    "status": "failed",
                    "error": "AssertionError: another cause",
                },
                {
                    "name": "tests/test_other.py::test_green",
                    "status": "passed",
                },
            ]
        },
        "playwright": {
            "tests": [
                {"file": "chat-flow.spec.ts", "status": "failed", "error": "Timeout"},
                {"file": "settings.spec.ts", "status": "timeout", "error": "Timeout"},
                {
                    "file": "signup-flow-stripe-managed.spec.ts",
                    "status": "failed",
                    "error": "Expected page",
                },
            ]
        },
        "vitest": {"tests": [{"name": "green unit", "status": "passed"}]},
    }

    embeds = run_tests._build_discord_failure_embeds(suites, color=0xEF4444)

    assert [embed["title"] for embed in embeds] == [
        "Playwright · 3 failures · 3 files",
        "Pytest unit · 2 failures · 2 files",
    ]
    playwright = embeds[0]["description"]
    assert "🔴 Billing & payments: **1** failed file" in playwright
    assert "🔴 Signup & authentication: **1** failed file" in playwright
    assert "🔴 Core chat: **1** failed file" in playwright
    assert "**Signup & authentication · 1 failure · 1 file**" in playwright
    assert "• `signup-flow-stripe-managed.spec.ts`" in playwright
    assert "**Core chat · 1 failure · 1 file**" in playwright
    assert "• `chat-flow.spec.ts`" in playwright
    assert "**Settings & account · 1 failure · 1 file**" in playwright
    assert "• `settings.spec.ts`" in playwright

    pytest = embeds[1]["description"]
    assert "🔴 Billing & payments: **1** failed file" in pytest
    assert "🔴 Signup & authentication: **1** failed file" in pytest
    assert "🟢 Core chat: **0** failed files" in pytest
    assert "• `tests/test_billing_routes.py`" in pytest
    assert "• `tests/test_settings_account_delete_force_logout.py`" in pytest

    rendered = "\n".join(embed["description"] for embed in embeds)
    assert "KeyError" not in rendered
    assert "AssertionError" not in rendered
    assert "Expected page" not in rendered


def test_discord_summary_payload_uses_grouped_failure_embeds(monkeypatch):
    run_tests = load_run_tests_module()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_tests.urllib.request, "urlopen", fake_urlopen)
    result = run_tests.RunResult(
        run_id="2026-08-03T03:00:02Z",
        git_sha="79b5ef7b5",
        git_branch="dev",
        environment="development",
        duration_seconds=15438.5,
        summary={
            "total": 3,
            "passed": 1,
            "failed": 2,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={
            "pytest_unit": {
                "tests": [
                    {
                        "name": "tests/test_apps_api.py::test_first_case",
                        "status": "failed",
                        "error": "KeyError: must not be sent",
                    },
                    {
                        "name": "tests/test_apps_api.py::test_second_case",
                        "status": "failed",
                        "error": "AssertionError: must not be sent",
                    },
                    {"name": "tests/test_other.py::test_green", "status": "passed"},
                ]
            }
        },
    )

    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service._send_summary_to_discord(result, webhook_url="https://example.invalid/webhook")

    embeds = captured["payload"]["embeds"]
    assert len(embeds) == 2
    assert embeds[0]["title"] == "❌ development nightly — 2 failed"
    assert embeds[1]["title"] == "Pytest unit · 2 failures · 1 file"
    details = embeds[1]["description"]
    assert "🔴 Signup & authentication: **0** failed files" not in details
    assert "🟢 Signup & authentication: **0** failed files" in details
    assert "• `tests/test_apps_api.py` — 2 failures" in details
    assert "KeyError" not in details
    assert "AssertionError" not in details
    assert "```" not in details
    assert captured["timeout"] == 30


def test_daily_notifications_include_structural_cache_backfill_status_without_detail():
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={"total": 1, "passed": 1, "failed": 0, "dispatch_error": 0, "timeout": 0, "result_unknown": 0, "skipped": 0, "not_started": 0},
        suites={},
        flags={"cache_backfill": {"status": "failed", "spec": "cache.spec.ts", "cache_group": "cache_group", "detail": "secret prompt must not be sent"}},
    )
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)

    text = service._build_summary_text(result)
    html = service._build_summary_html(result)

    assert "Cache backfill: failed (cache.spec.ts, cache_group)" in text
    assert "Cache backfill: failed (cache.spec.ts, cache_group)" in html
    assert "secret prompt" not in text
    assert "secret prompt" not in html


def test_summary_email_prefers_direct_brevo_when_both_transports_are_configured(monkeypatch):
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={
            "total": 1,
            "passed": 1,
            "failed": 0,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={},
    )
    calls = []
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.invalid"
    service.internal_token = "internal-token"
    service.brevo_api_key = "brevo-key"
    service.discord_webhook_url = "https://example.invalid/webhook"
    service._send_via_internal_api = lambda endpoint, payload: calls.append(("internal", endpoint)) or True
    service._send_via_brevo = lambda *_args: calls.append(("brevo", None)) or True
    service._send_summary_to_discord = lambda *_args, **_kwargs: True
    service.send_urgent_essential_failure_email = lambda *_args: None

    delivered = service.send_summary_email(result)

    assert delivered is True
    assert calls == [("brevo", None)]
    assert result.flags["email_delivered"] is True
    assert result.flags["discord_delivered"] is True
    assert result.flags["notification_channels"] == {
        "email": {"configured": True, "status": "provider_accepted", "transport": "brevo"},
        "discord": {"configured": True, "status": "provider_accepted", "transport": "webhook"},
    }


def test_summary_email_falls_back_to_internal_queue_when_brevo_fails():
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={
            "total": 1,
            "passed": 1,
            "failed": 0,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={},
    )
    calls = []
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.invalid"
    service.internal_token = "internal-token"
    service.brevo_api_key = "brevo-key"
    service.discord_webhook_url = "https://example.invalid/webhook"
    service._send_via_internal_api = lambda endpoint, payload: calls.append(("internal", endpoint)) or True
    service._send_via_brevo = lambda *_args: calls.append(("brevo", None)) or False
    service._send_summary_to_discord = lambda *_args, **_kwargs: True
    service.send_urgent_essential_failure_email = lambda *_args: None

    delivered = service.send_summary_email(result)

    assert delivered is False
    assert calls == [
        ("brevo", None),
        ("internal", "dispatch-test-summary-email"),
    ]
    assert result.flags["email_delivered"] is False
    assert result.flags["notification_channels"]["email"] == {
        "configured": True,
        "status": "queued_unconfirmed",
        "transport": "internal_api",
    }


def test_summary_email_is_delivered_when_optional_discord_is_unconfigured():
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={
            "total": 1,
            "passed": 1,
            "failed": 0,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={},
    )
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.invalid"
    service.internal_token = "internal-token"
    service.brevo_api_key = "brevo-key"
    service.discord_webhook_url = ""
    service._send_via_brevo = lambda *_args: True
    service._send_summary_to_discord = lambda *_args, **_kwargs: False
    service.send_urgent_essential_failure_email = lambda *_args: None

    assert service.send_summary_email(result) is True
    assert result.flags["email_delivered"] is True
    assert result.flags["discord_delivered"] is False


def test_summary_notifications_are_incomplete_when_configured_discord_fails():
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={
            "total": 1,
            "passed": 1,
            "failed": 0,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={},
    )
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.invalid"
    service.internal_token = "internal-token"
    service.brevo_api_key = "brevo-key"
    service.discord_webhook_url = "https://example.invalid/webhook"
    service._send_via_brevo = lambda *_args: True
    service._send_summary_to_discord = lambda *_args, **_kwargs: False
    service.send_urgent_essential_failure_email = lambda *_args: None

    assert service.send_summary_email(result) is False
    assert result.flags["email_delivered"] is True
    assert result.flags["discord_delivered"] is False


def test_manual_start_email_preserves_manual_trigger_type(monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.delenv("DAILY_RUN_ENVIRONMENT", raising=False)
    payloads = []
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.invalid"
    service._send_email = lambda _subject, _text, endpoint, payload: payloads.append((endpoint, payload)) or True

    service.send_start_email("abc123", "dev", "development")

    assert payloads[0][0] == "dispatch-test-start-email"
    assert payloads[0][1]["trigger_type"] == "Manual"


def test_daily_discord_status_reports_phase_and_elapsed_time(monkeypatch):
    run_tests = load_run_tests_module()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_tests.urllib.request, "urlopen", fake_urlopen)
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.discord_webhook_url = "https://example.invalid/webhook"

    service.send_daily_discord_status(
        "1234567890",
        "dev",
        "development",
        "2026-08-05T03:00:00Z",
        3670,
        "Apple remote",
    )

    embed = captured["payload"]["embeds"][0]
    assert embed["title"] == "⏳ development nightly — still running"
    assert "**Phase:** Apple remote" in embed["description"]
    assert "**Elapsed:** 61m" in embed["description"]
    assert run_tests.DAILY_STATUS_INTERVAL_SECONDS == 30 * 60
    assert captured["timeout"] == 30


def test_all_problem_statuses_fail_the_runner():
    run_tests = load_run_tests_module()
    empty = {
        "failed": 0,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "not_started": 0,
    }

    assert run_tests._exit_code_for_summary(empty) == 0
    for status in empty:
        assert run_tests._exit_code_for_summary({**empty, status: 1}) == 1


def test_daily_skip_notification_reports_no_commit_skip(monkeypatch):
    run_tests = load_run_tests_module()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_tests.urllib.request, "urlopen", fake_urlopen)
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.discord_webhook_url = "https://example.invalid/webhook"

    service.send_daily_skip_notification(
        "1234567890abcdef",
        "dev",
        "development",
        "2026-08-20T03:00:00Z",
        "No git commits in the last 24 hours.",
    )

    embed = captured["payload"]["embeds"][0]
    assert embed["title"] == "⏭️ development nightly — skipped"
    assert "**Reason:** No git commits in the last 24 hours." in embed["description"]
    assert "**Tests dispatched:** none" in embed["description"]
    assert "**Git:** `12345678@dev`" in embed["description"]
    assert embed["color"] == 0xF59E0B
    assert captured["timeout"] == 30


def test_daily_gate_notifies_when_no_commits(monkeypatch):
    run_tests = load_run_tests_module()
    events = []

    class FakeNotification:
        dot_env = {"E2E_DAILY_RUN_ENABLED": "true"}

        def send_daily_skip_notification(self, *args):
            events.append(args)

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.notification = FakeNotification()
    orchestrator.force = False
    orchestrator.git_sha = "1234567890abcdef"
    orchestrator.git_branch = "dev"
    orchestrator.environment = "development"
    orchestrator.run_id = "2026-08-20T03:00:00Z"

    monkeypatch.delenv("E2E_DAILY_RUN_ENABLED", raising=False)
    monkeypatch.setattr(run_tests.subprocess, "check_output", lambda *_args, **_kwargs: "")

    assert orchestrator._daily_gate() is False
    assert events == [(
        "1234567890abcdef",
        "dev",
        "development",
        "2026-08-20T03:00:00Z",
        "No git commits in the last 24 hours.",
    )]


def test_daily_status_starts_discord_before_email_and_uses_30_minute_cadence(monkeypatch):
    run_tests = load_run_tests_module()
    events = []

    class FakeNotification:
        def send_daily_discord_status(self, *_args, **kwargs):
            events.append("discord-start" if kwargs.get("started") else "discord-update")

        def send_start_email(self, *_args):
            events.append("email-start")

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            assert name == "daily-test-discord-status"
            assert daemon is True

        def start(self):
            events.append("thread-start")

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.notification = FakeNotification()
    orchestrator.git_sha = "1234567890"
    orchestrator.git_branch = "dev"
    orchestrator.environment = "development"
    orchestrator.run_id = "2026-08-05T03:00:00Z"
    orchestrator.current_phase = "starting"
    orchestrator._daily_status_thread = None
    monkeypatch.setattr(run_tests.threading, "Thread", FakeThread)

    orchestrator._start_daily_status_updates(100.0)

    assert events == ["discord-start", "thread-start", "email-start"]

    waits = []

    class FakeStop:
        def wait(self, timeout):
            waits.append(timeout)
            return len(waits) == 2

    orchestrator._daily_status_stop = FakeStop()
    monotonic_values = iter([100.0, 1900.0, 1900.0])
    monkeypatch.setattr(run_tests.time, "monotonic", lambda: next(monotonic_values))

    orchestrator._send_daily_status_updates(100.0)

    assert waits == [1800.0, 1800.0]
    assert events[-1] == "discord-update"


def test_vitest_artifact_records_the_failed_test_file(tmp_path):
    run_tests = load_run_tests_module()
    artifact = tmp_path / "vitest-results.json"
    artifact.write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "frontend/packages/ui/src/chat/chat.test.ts",
                        "assertionResults": [
                            {
                                "fullName": "chat renders a message",
                                "status": "failed",
                                "duration": 12,
                                "failureMessages": ["cause omitted from Discord"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    tests = run_tests.TestOrchestrator._parse_unit_test_artifact(tmp_path, "vitest")

    assert tests[0]["file"] == "frontend/packages/ui/src/chat/chat.test.ts"


def test_unit_artifact_counts_vitest_collection_failures_and_node_cli_tests(tmp_path):
    run_tests = load_run_tests_module()
    (tmp_path / "vitest-ui.json").write_text(
        json.dumps({
            "success": False,
            "testResults": [
                {
                    "name": "frontend/packages/ui/src/chat/chat.test.ts",
                    "status": "passed",
                    "assertionResults": [{"fullName": "chat renders", "status": "passed", "duration": 5}],
                },
                {
                    "name": "frontend/packages/ui/src/files/file.test.ts",
                    "status": "failed",
                    "message": "document is not defined",
                    "assertionResults": [],
                },
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "cli-account-import-tests.txt").write_text(
        "  ✔ parses an account archive (3.5ms)\n"
        "  ✖ rejects a corrupt archive (1.25ms)\n"
        "ℹ tests 2\n",
        encoding="utf-8",
    )

    tests = run_tests.TestOrchestrator._parse_unit_test_artifact(tmp_path, "vitest")

    assert [(test["name"], test["status"]) for test in tests] == [
        ("chat renders", "passed"),
        ("frontend/packages/ui/src/files/file.test.ts", "failed"),
        ("parses an account archive", "passed"),
        ("rejects a corrupt archive", "failed"),
    ]
    assert tests[1]["error"] == "document is not defined"
    assert tests[2]["duration_seconds"] == 0.004
    assert "file" not in tests[2]


def test_unit_artifact_reports_incomplete_node_cli_result_parsing(tmp_path):
    run_tests = load_run_tests_module()
    (tmp_path / "cli-account-import-tests.txt").write_text(
        "  ✔ parses an account archive (3.5ms)\n"
        "unrecognized reporter output\n"
        "ℹ tests 2\n",
        encoding="utf-8",
    )

    tests = run_tests.TestOrchestrator._parse_unit_test_artifact(tmp_path, "vitest")

    assert tests[-1]["status"] == "failed"
    assert tests[-1]["error"] == "Parsed 1 of 2 Node test results"


def test_failed_unit_workflow_is_not_masked_by_passing_partial_artifact(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.campaign_test_labels = []
    recent_calls = 0

    class FakeClient:
        def _recent_run_ids(self, **_kwargs):
            nonlocal recent_calls
            recent_calls += 1
            return [111] if recent_calls == 1 else [222, 111]

        def wait_for_runs(self, _run_ids, **_kwargs):
            return {222: {"conclusion": "failure"}}

        def download_artifact(self, _run_id, _artifact_name, artifact_dir):
            (artifact_dir / "pytest-results.json").write_text(
                json.dumps({
                    "tests": [{"nodeid": "tests/test_sdk.py::test_ok", "outcome": "passed", "duration": 0.1}],
                }),
                encoding="utf-8",
            )
            return artifact_dir

        def get_failed_job_error(self, _run_id):
            return "pytest exited with code 3"

    monkeypatch.setattr(run_tests, "GitHubActionsClient", FakeClient)
    monkeypatch.setattr(run_tests.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(run_tests.tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path))

    result = orchestrator._run_unit_suite_via_gha("pytest-unit.yml", "pytest-results")

    assert result.status == "failed"
    assert any(test["status"] == "failed" and "code 3" in test["error"] for test in result.tests)


def test_discord_description_truncates_at_file_boundaries_with_omission_count():
    run_tests = load_run_tests_module()
    lines = ["Summary", "", "**Failed test files:**", "**Playwright**"]
    lines.extend(f"• `very-long-test-file-{index:03d}.spec.ts`" for index in range(200))

    description = run_tests._fit_discord_description(lines)

    assert len(description) <= run_tests.DISCORD_DESCRIPTION_MAX_CHARS
    assert "more failed files; see the full test report." in description
    assert not description.splitlines()[-2].endswith("...")


def test_product_area_matching_avoids_generic_message_false_positive():
    run_tests = load_run_tests_module()

    assert run_tests._primary_product_area("tests/test_validation.py shows error message") == (
        run_tests.DEFAULT_PRODUCT_AREA
    )
    assert run_tests._primary_product_area("frontend/chat/composer.test.ts") == "Core chat"


def test_discord_failure_embeds_respect_message_embed_limit():
    run_tests = load_run_tests_module()
    embeds = [
        {"title": f"Suite {index}", "description": "failure", "color": 0xEF4444}
        for index in range(12)
    ]

    limited = run_tests._limit_discord_failure_embeds(embeds, color=0xEF4444)

    assert len(limited) == run_tests.DISCORD_MAX_EMBEDS - 1
    assert limited[-1]["title"] == "4 more failing suites"
    assert "• Suite 8" in limited[-1]["description"]
    assert "• Suite 11" in limited[-1]["description"]


def test_discord_failure_embeds_respect_aggregate_character_limit():
    run_tests = load_run_tests_module()
    critical = [
        "**Critical product areas**",
        "🔴 Billing & payments: **1** failed file",
        "🟢 Signup & authentication: **0** failed files",
        "🟢 Core chat: **0** failed files",
        "",
        "**Files by product area**",
    ]
    details = []
    for suite_index in range(4):
        lines = [*critical, "**Billing & payments · 100 failures · 100 files**"]
        lines.extend(
            f"• `suite-{suite_index}-very-long-failed-file-{file_index:03d}.spec.ts`"
            for file_index in range(100)
        )
        details.append({
            "title": f"Suite {suite_index} · 100 failures · 100 files",
            "description": run_tests._fit_discord_description(lines),
            "color": 0xEF4444,
        })
    summary = {"title": "Nightly summary", "description": "93 failed", "color": 0xEF4444}

    fitted = run_tests._fit_discord_embed_total([summary, *details])

    total_chars = sum(
        len(embed["title"]) + len(embed["description"])
        for embed in fitted
    )
    assert total_chars <= run_tests.DISCORD_EMBED_TOTAL_MAX_CHARS
    for embed in fitted[1:]:
        assert "**Critical product areas**" in embed["description"]
        assert "Billing & payments" in embed["description"]


def test_email_summaries_match_grouped_failure_structure_without_causes():
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="2026-08-03T03:00:02Z",
        git_sha="79b5ef7b5",
        git_branch="dev<script>alert(1)</script>",
        environment="development<img>",
        duration_seconds=15438.5,
        summary={
            "total": 4,
            "passed": 1,
            "failed": 3,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={
            "playwright": {
                "tests": [
                    {
                        "file": "signup-flow-stripe-managed.spec.ts",
                        "status": "failed",
                        "error": "Expected page: must not be emailed",
                    },
                    {
                        "file": "chat-flow.spec.ts",
                        "status": "failed",
                        "error": "Timeout: must not be emailed",
                    },
                    {"file": "green.spec.ts", "status": "passed"},
                ]
            },
            "pytest_unit": {
                "tests": [
                    {
                        "name": "tests/test_billing_routes.py::test_invoice",
                        "status": "failed",
                        "error": "KeyError: must not be emailed",
                    }
                ]
            },
        },
    )
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)

    text = service._build_summary_text(result)
    html = service._build_summary_html(result)

    assert "Playwright · 2 failures · 2 files" in text
    assert "Billing & payments: 1 failed file" in text
    assert "Signup & authentication: 1 failed file" in text
    assert "Core chat: 1 failed file" in text
    assert "signup-flow-stripe-managed.spec.ts" in text
    assert "chat-flow.spec.ts" in text
    assert "Pytest unit · 1 failure · 1 file" in text
    assert "tests/test_billing_routes.py" in text

    assert "Playwright · 2 failures · 2 files" in html
    assert "Billing &amp; payments: 1 failed file" in html
    assert "signup-flow-stripe-managed.spec.ts" in html
    assert "tests/test_billing_routes.py" in html
    assert "dev&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "development&lt;img&gt;" in html
    assert "<script>" not in html
    assert "development<img>" not in html

    for cause in ("Expected page", "Timeout", "KeyError", "must not be emailed"):
        assert cause not in text
        assert cause not in html


def test_internal_email_payload_uses_canonical_grouped_failures():
    run_tests = load_run_tests_module()
    result = run_tests.RunResult(
        run_id="2026-08-07T03:00:01Z",
        git_sha="e5c186d82",
        git_branch="dev",
        environment="development",
        duration_seconds=120,
        summary={
            "total": 2,
            "passed": 0,
            "failed": 2,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={
            "playwright": {
                "tests": [
                    {
                        "file": "signup-flow-stripe-managed.spec.ts",
                        "status": "failed",
                        "error": "Expected page: must not be emailed",
                    },
                    {
                        "file": "chat-flow.spec.ts",
                        "status": "failed",
                        "error": "Timeout: must not be emailed",
                    },
                ]
            }
        },
    )
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.test"

    payload = service._build_internal_api_payload(result)

    assert payload["subject_override"] == "[OpenMates] 2 failed (development)"
    assert payload["summary_copy"] == {
        "header_failure": "2 failed",
        "status_failure": "2 FAILED",
    }
    assert payload["failure_groups"] == [
        {
            "title": "Playwright · 2 failures · 2 files",
            "description": (
                "Critical product areas\n"
                "FAIL Billing & payments: 1 failed file\n"
                "FAIL Signup & authentication: 1 failed file\n"
                "FAIL Core chat: 1 failed file\n\n"
                "Files by product area\n"
                "Signup & authentication · 1 failure · 1 file\n"
                "- signup-flow-stripe-managed.spec.ts\n"
                "Core chat · 1 failure · 1 file\n"
                "- chat-flow.spec.ts"
            ),
        }
    ]
    assert "must not be emailed" not in json.dumps(payload["failure_groups"])


def test_internal_email_failure_groups_are_bounded():
    run_tests = load_run_tests_module()
    failed_tests = [
        {"file": f"very-long-chat-failure-{index:04d}.spec.ts", "status": "failed"}
        for index in range(500)
    ]
    result = run_tests.RunResult(
        run_id="2026-08-07T03:00:01Z",
        git_sha="e5c186d82",
        git_branch="dev",
        environment="development",
        duration_seconds=120,
        summary={
            "total": 500,
            "passed": 0,
            "failed": 500,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={"playwright": {"tests": failed_tests}},
    )
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "admin@example.test"

    groups = service._build_internal_api_payload(result)["failure_groups"]

    assert groups
    assert all(
        len(group["description"]) <= run_tests.DISCORD_DESCRIPTION_MAX_CHARS
        for group in groups
    )
