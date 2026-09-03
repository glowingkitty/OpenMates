"""Deterministic contract tests for daily recovery orchestration.

The suite covers critical classification and phase order, atomic GitHub
dispatch admission, truthful infrastructure results, bounded notifications,
and the opt-in recovery milestone without contacting external services.
"""

from __future__ import annotations

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: direct surface=cli assertions=test-orchestration.critical.registry-audited
def test_critical_registry_is_complete_and_new_chat_specs_require_classification(monkeypatch) -> None:
    run_tests = load_module("daily_recovery_registry", ROOT / "scripts" / "run_tests.py")
    assert run_tests.audit_critical_test_registry() == []
    active = [entry for entry in run_tests.CRITICAL_TEST_REGISTRY if entry["active"]]
    assert {entry["category"] for entry in active} == {"billing", "signup_auth", "core_chat"}
    assert all(entry["reason"].strip() for entry in active)

    monkeypatch.setattr(
        run_tests,
        "CRITICAL_TEST_REGISTRY",
        tuple(entry for entry in run_tests.CRITICAL_TEST_REGISTRY if entry["spec"] != "chat-search-flow.spec.ts"),
    )
    assert "likely critical spec is unclassified: chat-search-flow.spec.ts" in run_tests.audit_critical_test_registry()


# contract-test: direct surface=cli assertions=test-orchestration.daily.critical-first-broad-continues
def test_daily_phases_are_disjoint_and_broad_runs_after_critical_failure() -> None:
    run_tests = load_module("daily_recovery_phases", ROOT / "scripts" / "run_tests.py")
    phases = run_tests.daily_playwright_phases([
        "settings.spec.ts",
        "chat-flow.spec.ts",
        "signup-flow-passkey.spec.ts",
        "embeds.spec.ts",
    ])
    assert phases == {
        "critical": ["chat-flow.spec.ts", "signup-flow-passkey.spec.ts"],
        "broad": ["settings.spec.ts", "embeds.spec.ts"],
    }
    calls = []

    def run_phase(name: str, specs: list[str]):
        calls.append((name, specs))
        return run_tests.SuiteResult(status="failed" if name == "critical" else "passed")

    results = run_tests.execute_daily_playwright_phases(phases, run_phase)
    assert [name for name, _specs in calls] == ["critical", "broad"]
    assert results["critical"].status == "failed"
    assert results["broad"].status == "passed"


# contract-test: direct surface=cli assertions=test-orchestration.daily.critical-first-broad-continues,test-orchestration.results.infrastructure-is-not-product-failure
def test_daily_registry_failure_is_reported_without_suppressing_playwright() -> None:
    run_tests = load_module("daily_recovery_registry_failure", ROOT / "scripts" / "run_tests.py")
    calls = []

    def run_phase(name: str, specs: list[str]):
        calls.append((name, specs))
        return run_tests.SuiteResult(
            status="passed",
            tests=[{"name": spec, "file": spec, "status": "passed"} for spec in specs],
        )

    results = run_tests.execute_daily_playwright_phases(
        {"critical": ["critical.spec.ts"], "broad": ["broad.spec.ts"]},
        run_phase,
        ["stale registry entry"],
    )

    assert calls == [
        ("critical", ["critical.spec.ts"]),
        ("broad", ["broad.spec.ts"]),
    ]
    assert results["critical"].tests[0]["status"] == "passed"
    assert results["broad"].tests[0]["status"] == "passed"
    assert results["registry"].tests == [{
        "name": "critical-test-registry",
        "file": "scripts/run_tests.py",
        "status": "infrastructure_incident",
        "error": "stale registry entry",
    }]


# contract-test: direct surface=cli assertions=test-orchestration.dispatch.quota-aware-circuit-breaker
def test_parallel_dispatch_reservations_are_atomic() -> None:
    run_tests = load_module("daily_recovery_budget", ROOT / "scripts" / "run_tests.py")
    circuit = run_tests.DispatchCircuit()
    circuit.configure_budget(remaining=27, reset_at=1_778_000_000)
    barrier = Barrier(3)

    def reserve() -> bool:
        barrier.wait()
        return circuit.reserve_requests(1)

    with ThreadPoolExecutor(max_workers=3) as executor:
        admitted = list(executor.map(lambda _index: reserve(), range(3)))
    assert sorted(admitted) == [False, True, True]
    assert circuit.snapshot()["open"] is True


# contract-test: direct surface=cli assertions=test-orchestration.dispatch.quota-aware-circuit-breaker,test-orchestration.results.infrastructure-is-not-product-failure
def test_rate_limit_emits_one_parent_and_blocks_all_dependants(monkeypatch) -> None:
    run_tests = load_module("daily_recovery_rate_limit", ROOT / "scripts" / "run_tests.py")

    class Client:
        def __init__(self) -> None:
            self.dispatch_circuit = run_tests.DispatchCircuit()
            self.last_dispatch_error = ""
            self.calls = 0

        def refresh_dispatch_budget(self, _required: int):
            return self.dispatch_circuit.snapshot()

        def request_spec_dispatch(self, *_args, **_kwargs):
            self.calls += 1
            self.dispatch_circuit.open_rate_limit(reset_at=1_778_000_000)
            self.last_dispatch_error = "GitHub Actions rate limit blocked workflow dispatch"
            return None

    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)
    client = Client()
    result = run_tests.BatchRunner(
        client=client,
        specs=["one.spec.ts", "two.spec.ts", "three.spec.ts"],
        batch_size=1,
        fail_fast=False,
        coordinate_accounts=False,
    ).run_all_batches()
    assert client.calls == 1
    assert [test["status"] for test in result.tests] == [
        "infrastructure_incident",
        "blocked_by_parent",
        "blocked_by_parent",
        "blocked_by_parent",
    ]
    parent_key = "infrastructure::github-actions-dispatch"
    assert result.tests[0]["test_key"] == parent_key
    assert all(test["parent_incident_key"] == parent_key for test in result.tests[1:])


# contract-test: direct surface=cli assertions=test-orchestration.dispatch.quota-aware-circuit-breaker
def test_retry_requires_a_second_budget_reservation(monkeypatch) -> None:
    run_tests = load_module("daily_recovery_retry", ROOT / "scripts" / "run_tests.py")

    class Client:
        def __init__(self) -> None:
            self.dispatch_circuit = run_tests.DispatchCircuit()
            self.last_dispatch_error = "transient dispatch failure"
            self.calls = 0

        def refresh_dispatch_budget(self, required: int):
            self.dispatch_circuit.configure_budget(remaining=26, reset_at=1_778_000_000)
            self.dispatch_circuit.reserve_requests(required)

        def request_spec_dispatch(self, *_args, **_kwargs):
            self.calls += 1
            return None

    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)
    client = Client()
    result = run_tests.BatchRunner(
        client=client,
        specs=["one.spec.ts"],
        batch_size=1,
        fail_fast=False,
        coordinate_accounts=False,
    ).run_all_batches()
    assert client.calls == 1
    assert [test["status"] for test in result.tests] == ["infrastructure_incident", "blocked_by_parent"]


# contract-test: direct surface=cli assertions=test-orchestration.results.infrastructure-is-not-product-failure,test-orchestration.evidence.privacy-boundary
def test_results_and_provider_errors_are_truthful_and_sanitized() -> None:
    run_tests = load_module("daily_recovery_results", ROOT / "scripts" / "run_tests.py")
    result = run_tests.ResultAggregator.build_run_result(
        suites={"playwright": run_tests.SuiteResult(status="failed", tests=[
            {"name": "product", "status": "failed"},
            {"name": "dispatch", "status": "infrastructure_incident"},
            {"name": "blocked", "status": "blocked_by_parent"},
        ])},
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration=1,
        flags={},
    )
    assert result.summary["executed_product_failed"] == 1
    assert result.summary["infrastructure_incident"] == 1
    assert result.summary["blocked_by_parent"] == 1
    assert run_tests.github_dispatch_error_category(
        "HTTP 403 permission denied for token secret-value at private-host"
    ) == "permission_denied"


# contract-test: direct surface=cli assertions=test-orchestration.notifications.non-blocking-receipts,test-orchestration.evidence.privacy-boundary
def test_notification_exceptions_do_not_change_test_results() -> None:
    run_tests = load_module("daily_recovery_notifications", ROOT / "scripts" / "run_tests.py")
    result = run_tests.RunResult(
        run_id="run-1",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=1,
        summary={"total": 1, "passed": 1, "failed": 0, "dispatch_error": 0, "timeout": 0, "result_unknown": 0, "skipped": 0, "not_started": 0},
        suites={},
    )
    original = deepcopy(result.summary)
    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service.admin_email = "configured-recipient"
    service.internal_token = ""
    service.brevo_api_key = "configured-provider"
    service.discord_webhook_url = "configured-webhook"
    service._send_via_brevo = lambda *_args: (_ for _ in ()).throw(RuntimeError("secret-provider-detail"))
    service._send_summary_to_discord = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret-webhook-detail"))
    service.send_urgent_essential_failure_email = lambda *_args: None
    assert service.send_summary_email(result) is False
    assert result.summary == original
    assert result.flags["notification_channels"]["email"]["status"] == "failed"
    assert result.flags["notification_channels"]["discord"]["status"] == "failed"
    assert "secret" not in str(result.flags)


# contract-test: direct surface=cli assertions=test-orchestration.recovery.milestone
def test_milestone_requires_owned_remainder_accepted_channels_and_opt_in(monkeypatch) -> None:
    control = load_module("daily_recovery_control", ROOT / "scripts" / "tests.py")
    run_data = {
        "flags": {
            "daily": True,
            "suite": "all",
            "only_failed": False,
            "critical_phase": {"status": "passed"},
            "notification_channels": {
                "email": {"configured": True, "status": "provider_accepted", "transport": "brevo"},
                "discord": {"configured": True, "status": "provider_accepted", "transport": "webhook"},
            },
        },
        "summary": {"executed_product_failed": 1, "infrastructure_incident": 0, "blocked_by_parent": 0},
        "suites": {"playwright": {"tests": [
            {"file": "remaining.spec.ts", "status": "failed"},
        ]}},
    }
    complete = control.evaluate_daily_recovery_milestone(
        run_data,
        owned_failure_keys={"playwright::remaining.spec.ts"},
    )
    assert complete["complete"] is True
    assert control.evaluate_daily_recovery_milestone(run_data, owned_failure_keys=set())["complete"] is False
    queued = deepcopy(run_data)
    queued["flags"]["notification_channels"]["email"]["status"] = "queued_unconfirmed"
    assert control.evaluate_daily_recovery_milestone(
        queued,
        owned_failure_keys={"playwright::remaining.spec.ts"},
    )["complete"] is False

    monkeypatch.setattr(control, "_debug_campaign", lambda _key: {"completion_policy": {}})
    with pytest.raises(RuntimeError, match="--daily-recovery"):
        control.record_daily_recovery_milestone("normal", "run-1")


# contract-test: direct surface=cli assertions=test-orchestration.results.infrastructure-is-not-product-failure
def test_control_plane_counts_infrastructure_parent_without_skipping_it() -> None:
    control = load_module("daily_recovery_control_summary", ROOT / "scripts" / "tests.py")
    parent = "infrastructure::github-actions-dispatch"
    summary = control.summarize_current_tests({
        parent: {"test_key": parent, "status": "infrastructure_incident", "lane": "deterministic"},
        "playwright::blocked.spec.ts": {
            "status": "blocked_by_parent",
            "parent_incident_key": parent,
            "lane": "deterministic",
        },
    })
    assert summary["infrastructure_incident"] == 1
    assert summary["blocked_by_parent"] == 1
    assert summary["skipped"] == 0
