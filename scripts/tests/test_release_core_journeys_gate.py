"""Contract tests for the dev-to-main core journeys release gate.

These checks keep the canonical suite, GitHub workflow, and dev-host backend
attestation aligned without contacting GitHub, Vercel, or Docker. Runtime
verification remains a separate advisory release-gate step.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_HOURLY_SPECS = [
    "chat-flow.spec.ts",
    "settings-buy-credits-stripe-managed.spec.ts",
    "signup-flow-stripe-managed.spec.ts",
    "dev-smoke/dev-smoke-reachability.spec.ts",
]
EXPECTED_RELEASE_BASELINE = {
    "chat-flow.spec.ts",
    "dev-smoke/dev-smoke-reachability.spec.ts",
    "buy-credits-flow.spec.ts",
    "referral-signup-purchase.spec.ts",
    "saved-payment-invoice-flow.spec.ts",
    "settings-buy-credits-bank-transfer.spec.ts",
    "settings-buy-credits-stripe-eu.spec.ts",
    "settings-buy-credits-stripe-managed.spec.ts",
    "settings-gift-card-bank-transfer.spec.ts",
    "settings-support-bank-transfer.spec.ts",
    "settings-support-stripe.spec.ts",
    "signup-2fa-reconnect-preview.spec.ts",
    "signup-flow-bank-transfer.spec.ts",
    "signup-flow-passkey.spec.ts",
    "signup-flow-stripe-eu.spec.ts",
    "signup-flow-stripe-managed.spec.ts",
    "signup-free-testing-credits.spec.ts",
    "signup-skip-2fa-flow.spec.ts",
    "usage-token-breakdown.spec.ts",
}
EXPECTED_RELEASE_ACCOUNTS = (2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 21, 22, 23, 24, 25, 26, 27, 1, 4)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_workflow(name: str) -> dict:
    path = ROOT / ".github" / "workflows" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def test_core_journey_manifest_is_canonical_and_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    run_tests = load_module("release_gate_run_tests", ROOT / "scripts" / "run_tests.py")

    assert run_tests.CORE_JOURNEY_SPECS == EXPECTED_HOURLY_SPECS
    assert run_tests.CORE_JOURNEY_ACCOUNT_SLOTS == (2, 3, 5, 6)
    assert run_tests.HOURLY_DEV_SPECS is run_tests.CORE_JOURNEY_SPECS
    assert run_tests.RELEASE_GATE_SPECS[:2] == list(run_tests.RELEASE_GATE_BASE_SPECS)
    assert run_tests.RELEASE_GATE_SPECS[2:] == sorted(run_tests.RELEASE_GATE_SPECS[2:])
    assert EXPECTED_RELEASE_BASELINE <= set(run_tests.RELEASE_GATE_SPECS)
    assert run_tests.RELEASE_GATE_ACCOUNT_SLOTS == EXPECTED_RELEASE_ACCOUNTS
    assert len(run_tests.RELEASE_GATE_SPECS) <= (
        len(run_tests.RELEASE_GATE_ACCOUNT_SLOTS) * run_tests.RELEASE_GATE_MAX_ACCOUNT_WAVES
    )
    for pattern in run_tests.RELEASE_GATE_SPEC_PATTERNS:
        matching_specs = {
            path.relative_to(run_tests.SPEC_DIR).as_posix()
            for path in run_tests.SPEC_DIR.rglob(pattern)
        }
        expected_specs = {
            spec for spec in matching_specs
            if not spec.startswith(run_tests.RELEASE_GATE_EXCLUDED_PREFIXES)
        }
        assert expected_specs <= set(run_tests.RELEASE_GATE_SPECS)
    assert not any(
        spec.startswith(run_tests.RELEASE_GATE_EXCLUDED_PREFIXES)
        for spec in run_tests.RELEASE_GATE_SPECS
    )
    for spec_name in run_tests.RELEASE_GATE_SPECS:
        assert (ROOT / "frontend" / "apps" / "web_app" / "tests" / spec_name).is_file()

    run_tests.print_core_journey_matrix()
    matrix = json.loads(capsys.readouterr().out)
    assigned_accounts = [entry["account"] for entry in matrix["include"]]
    assert len(assigned_accounts) == len(set(assigned_accounts))
    assert matrix == {
        "include": [
            {
                "spec": spec_name,
                "account": str(EXPECTED_RELEASE_ACCOUNTS[index % len(EXPECTED_RELEASE_ACCOUNTS)]),
            }
            for index, spec_name in enumerate(run_tests.RELEASE_GATE_SPECS)
        ]
    }

    orchestrator = run_tests.TestOrchestrator.__new__(run_tests.TestOrchestrator)
    orchestrator.spec = None
    orchestrator.core_journeys = True
    orchestrator.only_failed = False
    assert orchestrator._discover_specs() == run_tests.RELEASE_GATE_SPECS

    orchestrator.core_journeys = False
    assert "deep-research-real-inference.spec.ts" in orchestrator.EXCLUDED_SPECS
    assert "sub-chats-real-inference.spec.ts" in orchestrator.EXCLUDED_SPECS


def test_release_matrix_fails_closed_when_account_capacity_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_tests = load_module("release_gate_capacity", ROOT / "scripts" / "run_tests.py")
    monkeypatch.setattr(
        run_tests,
        "RELEASE_GATE_SPECS",
        [
            f"required-{index}.spec.ts"
            for index in range(
                len(run_tests.RELEASE_GATE_ACCOUNT_SLOTS) * run_tests.RELEASE_GATE_MAX_ACCOUNT_WAVES + 1
            )
        ],
    )

    with pytest.raises(RuntimeError, match="serialized account capacity"):
        run_tests.print_core_journey_matrix()


def test_release_workflow_has_stable_fail_closed_gate() -> None:
    workflow = load_workflow("release-core-journeys.yml")
    triggers = workflow_triggers(workflow)

    assert triggers["pull_request"]["branches"] == ["main"]
    assert "paths" not in triggers["pull_request"]
    assert "paths-ignore" not in triggers["pull_request"]
    assert triggers["workflow_dispatch"]["inputs"]["checkout_ref"]["required"] is True
    assert workflow["concurrency"]["cancel-in-progress"] is True

    jobs = workflow["jobs"]
    assert jobs["validate-source"]["permissions"] == {"contents": "read"}
    assert jobs["deployment-ready"]["permissions"]["statuses"] == "read"
    status_step = next(
        step for step in jobs["deployment-ready"]["steps"]
        if step.get("name") == "Require release candidate commit statuses"
    )
    assert 'require_context "Vercel"' in status_step["run"]
    assert 'require_context "$RELEASE_CONTEXT"' in status_step["run"]
    assert jobs["core-journeys"]["strategy"]["fail-fast"] is False
    assert jobs["core-journeys"]["with"]["checkout_ref"]
    assert jobs["core-journeys"]["with"]["allow_credential_updates"] is False
    assert "OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON" in jobs["core-journeys"]["secrets"]
    assert jobs["core-journeys-gate"]["if"] == "always()"
    assert jobs["core-journeys-gate"]["name"] == "Release Gate / Core Journeys"
    aggregate_step = jobs["core-journeys-gate"]["steps"][0]
    assert "needs.core-journeys.result" in aggregate_step["env"]["CORE_RESULT"]
    assert 'test "$CORE_RESULT" = "success"' in aggregate_step["run"]


def test_single_spec_workflow_is_reusable_and_serializes_accounts() -> None:
    workflow = load_workflow("playwright-spec.yml")
    triggers = workflow_triggers(workflow)

    assert "workflow_dispatch" in triggers
    assert triggers["workflow_call"]["inputs"]["checkout_ref"]["required"] is True
    assert triggers["workflow_call"]["inputs"]["allow_credential_updates"]["default"] is False
    assert "inputs.account" in workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] is False

    steps = workflow["jobs"]["run-spec"]["steps"]
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
    assert checkout["with"]["ref"] == "${{ inputs.checkout_ref }}"
    assert checkout["with"]["persist-credentials"] is False
    mutation_steps = [step for step in steps if step.get("name", "").startswith("Update ")]
    assert mutation_steps
    assert all("inputs.allow_credential_updates" in step["if"] for step in mutation_steps)
    account_env = next(step["env"] for step in steps if step.get("name") == "Load selected test account credentials")
    assert "secrets.TEST_ACCOUNT_EMAIL != ''" in account_env["DIRECT_EMAIL"]
    assert "github.event_name" not in account_env["DIRECT_EMAIL"]


def test_backend_attestation_preflight_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    prepare = load_module(
        "release_gate_prepare",
        ROOT / "scripts" / "prepare_release_candidate.py",
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        calls.append(command)
        outputs = {
            ("git", "branch", "--show-current"): "dev\n",
            ("git", "status", "--porcelain", "--", *prepare.BACKEND_RUNTIME_PATHS): "",
            ("git", "rev-parse", "HEAD"): "a" * 40 + "\n",
            ("git", "rev-parse", "origin/dev"): "a" * 40 + "\n",
        }
        key = tuple(command)
        if key not in outputs:
            raise AssertionError(f"Unexpected command: {command}")
        return prepare.CommandResult(returncode=0, stdout=outputs[key], stderr="")

    monkeypatch.setattr(prepare, "run_command", fake_run)
    assert prepare.preflight_release_candidate() == "a" * 40

    def dirty_run(command: list[str], **kwargs):
        result = fake_run(command, **kwargs)
        if command == ["git", "status", "--porcelain", "--", *prepare.BACKEND_RUNTIME_PATHS]:
            return prepare.CommandResult(returncode=0, stdout=" M backend/file.py\n", stderr="")
        return result

    monkeypatch.setattr(prepare, "run_command", dirty_run)
    with pytest.raises(prepare.PreparationError, match="backend runtime paths are not clean"):
        prepare.preflight_release_candidate()


def test_backend_attestation_resolves_control_plane_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare = load_module(
        "release_gate_prepare_root",
        ROOT / "scripts" / "prepare_release_candidate.py",
    )
    checkout_root = tmp_path / "agent-f3b8"
    git_dir = tmp_path / "main" / ".git"
    checkout_root.mkdir()
    git_dir.mkdir(parents=True)

    def fake_run(command: list[str], **kwargs):
        assert command == ["git", "rev-parse", "--git-common-dir"]
        assert kwargs["cwd"] == checkout_root
        return SimpleNamespace(returncode=0, stdout=str(git_dir), stderr="")

    monkeypatch.setattr(prepare.subprocess, "run", fake_run)

    assert prepare.resolve_control_plane_root(checkout_root) == git_dir.parent


def test_backend_attestation_uses_lock_services_health_and_exact_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare = load_module(
        "release_gate_prepare_contract",
        ROOT / "scripts" / "prepare_release_candidate.py",
    )

    assert prepare.CORE_SERVICES == (
        "api",
        "task-worker",
        "user-init-worker",
        "core-worker",
        "user-tasks-worker",
        "reminder-worker",
        "task-scheduler",
        "app-ai-worker",
    )
    assert prepare.RELEASE_STATUS_CONTEXT == "Dev Release Candidate / Prepared"
    assert prepare.managed_setup_command("f563") == [
        sys.executable,
        "scripts/sessions.py",
        "docker",
        "run-setup",
        "--session",
        "f563",
        "--service",
        "cms-setup",
        "--build",
    ]
    restart = prepare.managed_prepare_command("f563")
    assert restart[:7] == [
        sys.executable,
        "scripts/sessions.py",
        "docker",
        "restart",
        "--session",
        "f563",
        "--build",
    ]
    assert restart[7:] == [
        part
        for service in prepare.CORE_SERVICES
        for part in ("--service", service)
    ]
    assert "compose" not in restart
    commands: list[list[str]] = []
    monkeypatch.setattr(
        prepare,
        "run_command",
        lambda command, **_kwargs: commands.append(list(command))
        or prepare.CommandResult(0, "", ""),
    )
    prepare.verify_cloud_overlay()
    assert commands == [[
        sys.executable,
        "scripts/api_tests/test_cloud_overlay_boot.py",
        "--api-url",
        prepare.DEV_API_URL,
        "--cli-overlay",
        "--redact",
    ]]
    status = prepare.github_status_command(
        "b" * 40,
        "success",
        "Core dev services are healthy",
        "https://github.com/example/repo",
    )
    assert f"repos/{{owner}}/{{repo}}/statuses/{'b' * 40}" in status
    assert "state=success" in status
    assert f"context={prepare.RELEASE_STATUS_CONTEXT}" in status
    assert f"target_url=https://github.com/example/repo/commit/{'b' * 40}" in status


def test_backend_attestation_reuses_exact_vercel_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    prepare = load_module(
        "release_gate_prepare_vercel",
        ROOT / "scripts" / "prepare_release_candidate.py",
    )
    calls: list[tuple[str, dict[str, str]]] = []
    fake_runner = SimpleNamespace(
        _read_env_file=lambda: {"VERCEL_TOKEN": "<TOKEN>"},
        _wait_for_vercel_deployment=lambda commit, env: calls.append((commit, env)) or (True, ""),
    )
    monkeypatch.setattr(prepare, "load_test_runner", lambda: fake_runner)

    prepare.wait_for_exact_vercel("c" * 40)

    assert calls == [("c" * 40, {"VERCEL_TOKEN": "<TOKEN>"})]
