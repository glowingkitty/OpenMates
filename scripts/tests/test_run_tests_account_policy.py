#!/usr/bin/env python3
"""
Regression tests for Playwright credential-isolation policy.

These tests keep auth-mutating E2E specs from silently using regular shared
accounts. They exercise pure orchestration helpers so the policy can be checked
without dispatching GitHub Actions or touching real credentials.

Architecture: docs/specs/e2e-credential-isolation/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests", RUN_TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reserved_specs_use_reserved_accounts_for_single_spec_dispatch():
    run_tests = load_run_tests_module()

    for spec_name, expected_account in run_tests.RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC.items():
        plan = run_tests.build_playwright_dispatch_plan([spec_name], batch_size=20)
        assert plan == [(0, spec_name, expected_account)]


def test_regular_specs_use_normal_accounts_and_skip_reserved_slots():
    run_tests = load_run_tests_module()
    regular_specs = [f"regular-{index}.spec.ts" for index in range(13)]

    plan = run_tests.build_playwright_dispatch_plan(regular_specs, batch_size=20)
    assigned_accounts = [account for _batch, _spec, account in plan]

    assert assigned_accounts == list(run_tests.NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS)
    assert not set(assigned_accounts) & set(run_tests.RESERVED_PLAYWRIGHT_ACCOUNT_SLOTS)


def test_batch_size_is_capped_to_normal_account_pool():
    run_tests = load_run_tests_module()
    regular_specs = [f"regular-{index}.spec.ts" for index in range(14)]

    plan = run_tests.build_playwright_dispatch_plan(regular_specs, batch_size=20)

    assert plan[12] == (0, "regular-12.spec.ts", 13)
    assert plan[13] == (1, "regular-13.spec.ts", 1)


def test_dispatch_plan_can_use_preflight_available_normal_slots():
    run_tests = load_run_tests_module()
    regular_specs = [f"regular-{index}.spec.ts" for index in range(5)]

    plan = run_tests.build_playwright_dispatch_plan(
        regular_specs,
        batch_size=20,
        normal_account_slots=(1, 2),
    )

    assert plan == [
        (0, "regular-0.spec.ts", 1),
        (0, "regular-1.spec.ts", 2),
        (1, "regular-2.spec.ts", 1),
        (1, "regular-3.spec.ts", 2),
        (2, "regular-4.spec.ts", 1),
    ]


def test_preflight_availability_reduces_normal_pool_and_blocks_reserved_specs():
    run_tests = load_run_tests_module()
    preflight_results = [
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="passed", account=1),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="passed", account=2),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="skipped", account=3),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="skipped", account=14),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="passed", account=15),
    ]

    runnable, blocked, normal_slots, reason = run_tests._apply_preflight_account_availability(
        [
            "regular.spec.ts",
            "account-recovery-flow.spec.ts",
            "backup-code-login-flow.spec.ts",
        ],
        preflight_results,
    )

    assert runnable == ["regular.spec.ts", "backup-code-login-flow.spec.ts"]
    assert normal_slots == (1, 2)
    assert len(blocked) == 1
    assert blocked[0].file == "account-recovery-flow.spec.ts"
    assert blocked[0].status == "failed"
    assert blocked[0].account == 14
    assert reason is not None
    assert "Unavailable normal account slot(s)" in reason
    assert "account-recovery-flow.spec.ts (slot 14)" in reason


def test_single_regular_spec_falls_back_to_healthy_normal_account(monkeypatch):
    run_tests = load_run_tests_module()
    captured: dict[str, object] = {}
    preflight_calls: list[list[int] | None] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = "regular.spec.ts"
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator._discover_specs = lambda: ["regular.spec.ts"]

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        if accounts == [1]:
            return run_tests.SuiteResult(
                status="failed",
                tests=[{
                    "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "status": "failed",
                    "account": 1,
                }],
                reason="slot 1 failed",
            )
        return run_tests.SuiteResult(
            status="passed",
            tests=[{
                "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "status": "passed",
                "account": 2,
            }],
        )

    class FakeBatchRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_all_batches(self):
            return run_tests.SuiteResult(
                status="passed",
                tests=[{"name": "regular.spec.ts", "file": "regular.spec.ts", "status": "passed"}],
            )

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())
    monkeypatch.setattr(run_tests, "BatchRunner", FakeBatchRunner)

    result = orchestrator._run_playwright()

    assert result.status == "passed"
    assert preflight_calls == [[1], list(range(2, 14))]
    assert captured["normal_account_slots"] == (2,)
    assert result.reason == "Selected normal account slot 1 failed preflight; using fallback slot 2 for regular.spec.ts"


def test_single_reserved_spec_does_not_fall_back_when_reserved_account_fails(monkeypatch):
    run_tests = load_run_tests_module()
    preflight_calls: list[list[int] | None] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = "account-recovery-flow.spec.ts"
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator._discover_specs = lambda: ["account-recovery-flow.spec.ts"]

    expected = run_tests.SuiteResult(
        status="failed",
        tests=[{
            "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
            "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
            "status": "failed",
            "account": 14,
        }],
        reason="slot 14 failed",
    )

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        return expected

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())

    result = orchestrator._run_playwright()

    assert result is expected
    assert preflight_calls == [[14]]


def test_hourly_dev_specs_exist():
    run_tests = load_run_tests_module()
    tests_dir = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"

    missing_specs = [
        spec_name
        for spec_name in run_tests.HOURLY_DEV_SPECS
        if not (tests_dir / spec_name).is_file()
    ]

    assert missing_specs == []


def test_dispatch_run_matching_uses_unique_token():
    run_tests = load_run_tests_module()

    runs = [
        {"databaseId": 111, "displayTitle": "Playwright: chat-flow.spec.ts account 1 rt-other"},
        {"databaseId": 222, "displayTitle": "Playwright: test-account-preflight.spec.ts account 11 rt-target"},
    ]

    assert run_tests._matching_dispatched_run_id(runs, "rt-target") == 222
    assert run_tests._matching_dispatched_run_id(runs, "rt-missing") is None


def test_full_git_sha_expands_short_display_ref(monkeypatch):
    run_tests = load_run_tests_module()
    full_sha = "a" * 40
    commands: list[list[str]] = []

    def fake_check_output(command, **_kwargs):
        commands.append(command)
        return full_sha

    monkeypatch.setattr(run_tests.subprocess, "check_output", fake_check_output)

    assert run_tests._full_git_sha("abc123") == full_sha
    assert commands == [["git", "-C", str(PROJECT_ROOT), "rev-parse", "abc123"]]


def test_canceled_vercel_deployment_retries_once_before_ready(monkeypatch):
    run_tests = load_run_tests_module()
    deployments = iter([
        {"id": "dpl-canceled", "state": "CANCELED", "errorMessage": "transient cancellation"},
        {"id": "dpl-canceled", "state": "CANCELED", "errorMessage": "transient cancellation"},
        {"id": "dpl-ready", "state": "READY"},
    ])
    redeployed: list[str] = []

    monkeypatch.setattr(run_tests, "_vercel_project_config", lambda: ("team", "project"))
    monkeypatch.setattr(run_tests, "_latest_vercel_deployment_for_sha", lambda *_args: next(deployments))
    monkeypatch.setattr(
        run_tests,
        "_redeploy_vercel_deployment",
        lambda _token, _team, deployment_id: redeployed.append(deployment_id),
        raising=False,
    )
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    ready, reason = run_tests._wait_for_vercel_deployment("abc123", {"VERCEL_TOKEN": "test-token"})

    assert ready is True
    assert reason == ""
    assert redeployed == ["dpl-canceled"]


def test_undispatched_specs_are_recorded_as_not_started():
    run_tests = load_run_tests_module()

    tests = run_tests._not_started_playwright_specs(
        ["signup-flow-passkey.spec.ts", "settings-buy-credits-stripe-eu.spec.ts", "chat-flow.spec.ts"],
        "Vercel deployment dpl-canceled was canceled",
    )

    assert [test["name"] for test in tests] == [
        "signup-flow-passkey.spec.ts",
        "settings-buy-credits-stripe-eu.spec.ts",
        "chat-flow.spec.ts",
    ]
    assert {test["status"] for test in tests} == {"not_started"}
    assert {test["error"] for test in tests} == {"Vercel deployment dpl-canceled was canceled"}


def test_playwright_gate_reports_every_undispatched_spec(monkeypatch):
    run_tests = load_run_tests_module()
    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 1
    orchestrator.dry_run = False
    orchestrator.environment = "development"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator._discover_specs = lambda: ["signup-flow-passkey.spec.ts", "chat-flow.spec.ts"]
    monkeypatch.setattr(
        run_tests,
        "_wait_for_vercel_deployment",
        lambda _git_sha, _dot_env: (False, "Vercel deployment dpl-canceled was canceled"),
    )

    result = orchestrator._run_playwright()

    assert result.status == "failed"
    assert result.tests[0]["name"] == "vercel-deployment-gate"
    assert [test["status"] for test in result.tests[1:]] == ["not_started", "not_started"]
    assert [test["name"] for test in result.tests[1:]] == [
        "signup-flow-passkey.spec.ts",
        "chat-flow.spec.ts",
    ]


def test_dispatch_passes_full_checkout_ref_to_workflow(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    client = run_tests.GitHubActionsClient(
        git_sha="abc123",
    )
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(
        client,
        "_recent_runs",
        lambda limit=50: [{
            "databaseId": 123,
            "displayTitle": next(
                item.removeprefix("dispatch_token=")
                for item in commands[0]
                if item.startswith("dispatch_token=")
            ),
        }],
    )

    assert client.dispatch_spec("chat-flow.spec.ts", account=1) == 123
    assert "checkout_ref=abc123" in commands[0]


def test_preflight_account_payload_deduplicates_emails():
    run_tests = load_run_tests_module()

    results = [
        run_tests.SpecResult(name="test-account-preflight.spec.ts", status="passed", account=1, account_email="Test@Example.test"),
        run_tests.SpecResult(name="test-account-preflight.spec.ts", status="passed", account=2, account_email="test@example.test"),
        run_tests.SpecResult(name="test-account-preflight.spec.ts", status="passed", account=3, account_email=None),
    ]

    assert run_tests._configured_preflight_accounts(results) == [
        {"slot": 1, "email": "Test@Example.test"}
    ]


def test_extract_account_email_from_playwright_stdout(tmp_path):
    run_tests = load_run_tests_module()
    report = tmp_path / "playwright.json"
    report.write_text(
        '{"suites":[{"specs":[{"tests":[{"results":[{"stdout":['
        '{"text":"[ACCOUNT_PREFLIGHT][slot 1] Starting. | meta={\\"email\\":\\"acct@example.test\\"}\\n"}'
        ']}]}]}]}]}',
        encoding="utf-8",
    )

    assert run_tests.BatchRunner._extract_account_email_from_playwright_json(report) == "acct@example.test"


def test_playwright_json_passed_with_skipped_phases_is_not_an_error(tmp_path):
    run_tests = load_run_tests_module()
    report = tmp_path / "playwright.json"
    report.write_text(
        '{"suites":[{"specs":[{"tests":[{"results":['
        '{"status":"passed","steps":[]},'
        '{"status":"skipped","steps":[]}'
        ']}]}]}]}',
        encoding="utf-8",
    )

    extracted_err, errors, steps, result_statuses = (
        run_tests.BatchRunner._extract_structured_data_from_playwright_json(report)
    )

    assert extracted_err is None
    assert errors == []
    assert steps == []
    assert set(result_statuses) == {"passed", "skipped"}


def test_playwright_retry_pass_is_a_passing_flake(tmp_path):
    run_tests = load_run_tests_module()
    report = tmp_path / "playwright.json"
    report.write_text(
        '{"suites":[{"specs":[{"tests":[{"results":['
        '{"retry":0,"status":"failed","error":{"message":"first attempt"}},'
        '{"retry":1,"status":"passed"}'
        ']}]}]}]}',
        encoding="utf-8",
    )

    summary = run_tests.BatchRunner._playwright_attempt_summary(report)

    assert summary["terminal_statuses"] == ["passed"]
    assert summary["attempt_statuses"] == ["failed", "passed"]
    assert summary["retries"] == 1
    assert summary["flaky"] is True


def test_passing_flake_is_not_counted_as_a_final_failure():
    run_tests = load_run_tests_module()
    suite = run_tests.SuiteResult(
        status="passed",
        tests=[{"name": "example.spec.ts", "status": "passed", "flaky": True, "retries": 1}],
    )

    result = run_tests.ResultAggregator.build_run_result(
        {"playwright": suite}, "run-1", "sha", "dev", "development", 1.0, {}
    )

    assert result.summary["passed"] == 1
    assert result.summary["failed"] == 0


def test_flake_history_is_idempotent_by_run_id(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    data = {
        "run_id": "run-1",
        "suites": {"playwright": {"tests": [{
            "name": "example.spec.ts", "file": "example.spec.ts", "status": "passed",
            "flaky": True, "retries": 1, "attempt_statuses": ["failed", "passed"],
        }]}},
    }

    run_tests.record_flake_history(data)
    run_tests.record_flake_history(data)

    history = __import__("json").loads((tmp_path / "flaky-history.json").read_text(encoding="utf-8"))
    entry = history["tests"]["playwright::example.spec.ts"]
    assert entry["total_runs"] == 1
    assert entry["flaky_count"] == 1
    assert entry["last_attempt_statuses"] == ["failed", "passed"]


def test_credit_guard_pipes_local_script_into_api_container(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    guard_script = tmp_path / "backend" / "scripts" / "top_up_test_account_credits.py"
    guard_script.parent.mkdir(parents=True)
    guard_script.write_text("print('guard script')\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "PROJECT_ROOT", tmp_path)

    captured = {}

    def fake_run(cmd, input, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return SimpleNamespace(stdout="accounts_checked=1\nok slots=1 credits=50000\n", stderr="", returncode=0)

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    error = run_tests.TestOrchestrator._ensure_preflight_account_credits([
        run_tests.SpecResult(
            name="test-account-preflight.spec.ts",
            status="passed",
            account=1,
            account_email="acct@example.test",
        )
    ])

    assert error is None
    assert captured["cmd"][:6] == ["docker", "exec", "-i", "api", "python", "-"]
    assert captured["cmd"][6] == "--accounts-json"
    assert '"email": "acct@example.test"' in captured["cmd"][7]
    assert captured["input"] == "print('guard script')\n"
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 180


def test_credential_update_artifacts_are_persisted_outside_screenshots(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    artifact_root = tmp_path / "artifact"
    uploaded_artifacts = artifact_root / "frontend" / "apps" / "web_app" / "artifacts"
    uploaded_artifacts.mkdir(parents=True)
    (uploaded_artifacts / "new_otp_key.txt").write_text("OTP_PLACEHOLDER", encoding="utf-8")
    (uploaded_artifacts / "api_key.txt").write_text("API_KEY_PLACEHOLDER", encoding="utf-8")

    results_dir = tmp_path / "test-results"
    monkeypatch.setattr(run_tests, "RESULTS_DIR", results_dir)

    run_tests.BatchRunner._persist_credential_update_artifacts(
        "backup-code-login-flow.spec.ts",
        artifact_root,
    )

    dest = results_dir / "credential-updates" / "backup-code-login-flow"
    assert (dest / "new_otp_key.txt").read_text(encoding="utf-8") == "OTP_PLACEHOLDER"
    assert (dest / "api_key.txt").read_text(encoding="utf-8") == "API_KEY_PLACEHOLDER"
    assert not (results_dir / "screenshots" / "current" / "backup-code-login-flow" / "new_otp_key.txt").exists()
