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


def test_dispatch_run_matching_uses_unique_token():
    run_tests = load_run_tests_module()

    runs = [
        {"databaseId": 111, "displayTitle": "Playwright: chat-flow.spec.ts account 1 rt-other"},
        {"databaseId": 222, "displayTitle": "Playwright: test-account-preflight.spec.ts account 11 rt-target"},
    ]

    assert run_tests._matching_dispatched_run_id(runs, "rt-target") == 222
    assert run_tests._matching_dispatched_run_id(runs, "rt-missing") is None


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
