#!/usr/bin/env python3
"""
Regression tests for account-free Playwright component spec dispatch.

These tests keep isolated component previews from silently entering the shared
test-account pool. They exercise the Python dispatcher and workflow contract
without dispatching GitHub Actions or touching real credentials.

Architecture: docs/architecture/github-actions-ci.md
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"
WORKFLOW_PATH = PROJECT_ROOT / ".github/workflows/playwright-spec.yml"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests_unauthenticated", RUN_TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_component_message_input_spec_declares_exact_account_free_marker() -> None:
    run_tests = load_run_tests_module()

    assert not run_tests._playwright_spec_requires_account("component-message-input.spec.ts")


def test_account_free_marker_is_exact_and_fail_closed(tmp_path, monkeypatch) -> None:
    run_tests = load_run_tests_module()
    project_root = tmp_path / "repo"
    spec_dir = project_root / "frontend" / "apps" / "web_app" / "tests"
    spec_dir.mkdir(parents=True)
    marker = run_tests.PLAYWRIGHT_ACCOUNT_NOT_REQUIRED_MARKER
    (spec_dir / "marked.spec.ts").write_text(f"{marker}\n", encoding="utf-8")
    (spec_dir / "wrong-reason.spec.ts").write_text(
        "// playwright-account: not_required reason=other\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(run_tests, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(run_tests, "SPEC_DIR", spec_dir)

    assert not run_tests._playwright_spec_requires_account("marked.spec.ts")
    assert run_tests._playwright_spec_requires_account("wrong-reason.spec.ts")
    assert run_tests._playwright_spec_requires_account("missing.spec.ts")

    monkeypatch.setattr(
        run_tests.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="fatal"),
    )
    assert run_tests._playwright_spec_requires_account("marked.spec.ts", deployed_git_ref="abc123")


def test_account_free_dispatch_plan_does_not_consume_normal_slots() -> None:
    run_tests = load_run_tests_module()
    requirements = {
        "component.spec.ts": False,
        "first-auth.spec.ts": True,
        "second-auth.spec.ts": True,
    }

    plan = run_tests.build_playwright_dispatch_plan(
        ["component.spec.ts", "first-auth.spec.ts", "second-auth.spec.ts"],
        batch_size=3,
        normal_account_slots=(1, 2),
        requires_account_by_spec=requirements,
    )

    assert plan == [
        (0, "component.spec.ts", run_tests.ACCOUNT_FREE_WORKFLOW_ACCOUNT),
        (0, "first-auth.spec.ts", 1),
        (0, "second-auth.spec.ts", 2),
    ]
    assert run_tests._preflight_accounts_for_specs(
        ["component.spec.ts", "first-auth.spec.ts", "second-auth.spec.ts"],
        batch_size=3,
        requires_account_by_spec=requirements,
    ) == [1, 2]
    assert run_tests._preflight_accounts_for_specs(
        ["component.spec.ts"],
        batch_size=1,
        requires_account_by_spec={"component.spec.ts": False},
    ) == []


def test_account_free_batch_dispatch_skips_leases_credentials_and_fixtures(monkeypatch) -> None:
    run_tests = load_run_tests_module()
    dispatches: list[dict[str, object]] = []

    def fail_lease(*_args, **_kwargs):
        raise AssertionError("account-free specs must not acquire account leases")

    class FakeClient:
        last_dispatch_error = ""

        def request_spec_dispatch(self, spec, account, use_mocks=True, record_live_fixtures=False, **kwargs):
            dispatches.append({
                "spec": spec,
                "account": account,
                "use_mocks": use_mocks,
                "record_live_fixtures": record_live_fixtures,
                **kwargs,
            })
            return f"token-{len(dispatches)}"

        def resolve_dispatch_tokens(self, unresolved):
            return {token: index + 100 for index, token in enumerate(unresolved)}

        def wait_for_runs(self, run_ids, _fail_fast):
            return {run_id: {"status": "completed", "conclusion": "success"} for run_id in run_ids}

        def download_artifact(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(run_tests.session_control, "acquire_test_resource_lease", fail_lease)

    runner = run_tests.BatchRunner(
        client=FakeClient(),
        specs=["component-message-input.spec.ts"],
        batch_size=1,
        fail_fast=True,
        normal_account_slots=(),
        allow_credential_updates=True,
        seeded_gift_cards={
            "component-message-input.spec.ts": run_tests.SeededGiftCard(
                spec="component-message-input.spec.ts",
                code="E2E2-TEST-CARD",
                directus_id="gift-card-id",
                credits_value=run_tests.E2E_GIFT_CARD_REDEMPTION_CREDITS,
            )
        },
        requires_account_by_spec={"component-message-input.spec.ts": False},
        coordinate_accounts=True,
    )

    result = runner.run_all_batches()

    assert result.status == "passed"
    assert "account" not in result.tests[0]
    assert dispatches == [{
        "spec": "component-message-input.spec.ts",
        "account": run_tests.ACCOUNT_FREE_WORKFLOW_ACCOUNT,
        "use_mocks": True,
        "record_live_fixtures": False,
        "create_account_slot": None,
        "allow_credential_updates": False,
        "seeded_gift_card_code": None,
        "proof_video_profile": "",
        "daily_ai_run_id": "",
        "requires_account": False,
    }]


def test_single_account_free_orchestration_skips_account_preflight(monkeypatch) -> None:
    run_tests = load_run_tests_module()
    dispatches: list[dict[str, object]] = []

    class FakeClient:
        last_dispatch_error = ""

        def __init__(self, git_sha=None):
            self.git_sha = git_sha

        def request_spec_dispatch(self, spec, account, *_args, **kwargs):
            dispatches.append({"spec": spec, "account": account, **kwargs})
            return "token-1"

        def resolve_dispatch_tokens(self, unresolved):
            return {token: 123 for token in unresolved}

        def wait_for_runs(self, run_ids, _fail_fast):
            return {run_id: {"status": "completed", "conclusion": "success"} for run_id in run_ids}

        def download_artifact(self, *_args, **_kwargs):
            return None

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 1
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = "component-message-input.spec.ts"
    orchestrator.account = None
    orchestrator.create_account_slot = None
    orchestrator.core_journeys = False
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.proof_video_profile = ""
    orchestrator.daily = False
    orchestrator._discover_specs = lambda: ["component-message-input.spec.ts"]
    orchestrator._save_playwright_progress_snapshot = lambda _result: None
    orchestrator._share_dispatch_circuit = lambda _client: None

    monkeypatch.setattr(run_tests, "GitHubActionsClient", FakeClient)
    monkeypatch.setattr(
        orchestrator,
        "_run_account_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("account-free spec must not run account preflight")
        ),
    )

    result = orchestrator._run_playwright_with_runtime()

    assert result.status == "passed"
    assert dispatches == [{
        "spec": "component-message-input.spec.ts",
        "account": run_tests.ACCOUNT_FREE_WORKFLOW_ACCOUNT,
        "create_account_slot": None,
        "allow_credential_updates": False,
        "seeded_gift_card_code": None,
        "proof_video_profile": "",
        "daily_ai_run_id": "",
        "requires_account": False,
    }]


def test_github_dispatch_sends_account_requirement_input(monkeypatch) -> None:
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(
        run_tests.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    client = run_tests.GitHubActionsClient(git_sha="abc123")

    token = client.request_spec_dispatch(
        "component-message-input.spec.ts",
        account=run_tests.ACCOUNT_FREE_WORKFLOW_ACCOUNT,
        requires_account=False,
        allow_credential_updates=False,
    )

    assert token is not None
    assert "account=0" in commands[0]
    assert "requires_account=false" in commands[0]
    assert "allow_credential_updates=false" in commands[0]
    assert "checkout_ref=abc123" in commands[0]


def test_playwright_workflow_gates_account_only_steps_and_secrets() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "requires_account:" in workflow
    assert "Validate account-free spec marker" in workflow
    assert "// playwright-account: not_required reason=isolated_component_preview" in workflow
    assert "if: inputs.requires_account\n        env:" in workflow
    assert "if: inputs.requires_account && inputs.migrate_account_secrets_to_expanded_bundle" in workflow
    assert "if: inputs.requires_account && inputs.seeded_gift_card_code != ''" in workflow
    assert "if: inputs.requires_account\n        run: |\n          set -euo pipefail\n          mkdir -p frontend/apps/web_app/artifacts" in workflow
    assert "if: inputs.requires_account && inputs.spec == '__cli_integration_code_docs__'" in workflow
    assert "OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: ${{ inputs.requires_account && inputs.account || '' }}" in workflow
    assert "PLAYWRIGHT_WORKER_SLOT: ${{ inputs.requires_account && '1' || '' }}" in workflow
    assert "SIGNUP_TEST_EMAIL_DOMAINS: ${{ inputs.requires_account && secrets.SIGNUP_TEST_EMAIL_DOMAINS || '' }}" in workflow
    assert "GMAIL_CLIENT_ID: ${{ inputs.requires_account && secrets.GMAIL_CLIENT_ID || '' }}" in workflow
    assert "E2E_DAILY_AI_RUN_ID: ${{ inputs.requires_account && inputs.daily_ai_run_id || '' }}" in workflow
    assert "CREATE_ACCOUNT_SLOT: ${{ inputs.requires_account && inputs.create_account_slot || '' }}" in workflow
    assert "if: always() && inputs.requires_account && inputs.allow_credential_updates" in workflow
    assert "if: always() && inputs.requires_account\n        run: |\n          set -euo pipefail\n          if [ -z \"${OPENMATES_CI_API_KEY_ID:-}\" ]; then" in workflow
