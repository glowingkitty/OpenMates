#!/usr/bin/env python3
"""
Focused daily AI runner policy regression tests.

These cover manifest classifications and deterministic selection without
dispatching Playwright or calling inference providers. Architecture:
contracts/architecture/daily-ai-test-inference/.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "scripts" / "daily_ai_test_policy.py"
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"
AUDIT_PATH = PROJECT_ROOT / "scripts" / "audit_daily_ai_test_inference.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: direct surface=cli assertions=daily-ai-tests.real.fixed-plus-rotating,daily-ai-tests.validation.conditional-real-gate
def test_manifest_marks_costly_real_inference_specs_manual_expensive():
    policy = load_module("daily_ai_policy_classifications", POLICY_PATH)

    manifest = policy.load_manifest()

    assert manifest["specs"]["deep-research-real-inference.spec.ts"]["classification"] == policy.MANUAL_EXPENSIVE
    assert manifest["specs"]["sub-chats-real-inference.spec.ts"]["classification"] == policy.MANUAL_EXPENSIVE
    assert manifest["specs"]["application-preview-share.spec.ts"]["classification"] == policy.BACKFILL_PENDING
    assert manifest["daily_canaries"]["fixed"] == ["daily-ai-fixed-canary.spec.ts"]
    assert manifest["daily_canaries"]["rotating"] == ["daily-ai-rotating-canary.spec.ts"]


# contract-test: direct surface=cli assertions=daily-ai-tests.real.fixed-plus-rotating
def test_daily_canaries_fail_closed_when_credentials_are_missing():
    policy = load_module("daily_ai_policy_canary_prereqs", POLICY_PATH)
    manifest = policy.load_manifest()
    spec_dir = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"

    for canary in [*manifest["daily_canaries"]["fixed"], *manifest["daily_canaries"]["rotating"]]:
        source = (spec_dir / canary).read_text(encoding="utf-8")
        assert "test.skip(" not in source
        assert "requires configured test-account credentials" in source


# contract-test: direct surface=cli assertions=daily-ai-tests.validation.conditional-real-gate
def test_discovery_keeps_replay_and_non_ai_specs_but_excludes_unmarked_ai(tmp_path):
    policy = load_module("daily_ai_policy_discovery", POLICY_PATH)

    (tmp_path / "ordinary-non-ai.spec.ts").write_text("test('settings', () => {})")
    (tmp_path / "cached-ai.spec.ts").write_text("sendMessage(page); withLiveMockMarker('x', 'g')")
    (tmp_path / "unmarked-ai.spec.ts").write_text("sendMessage(page, 'real')")
    with pytest.raises(RuntimeError, match="Unclassified AI spec"):
        policy.discover_specs(["unmarked-ai.spec.ts"], manifest={
            "schema_version": 2,
            "specs": {},
            "daily_canaries": {"fixed": [], "rotating": []},
        }, spec_dir=tmp_path)
    discovered = policy.discover_specs(
        ["ordinary-non-ai.spec.ts", "cached-ai.spec.ts"], spec_dir=tmp_path
    )

    assert discovered == ["cached-ai.spec.ts", "ordinary-non-ai.spec.ts"]


# contract-test: direct surface=cli assertions=daily-ai-tests.real.fixed-plus-rotating
def test_daily_plan_selects_one_fixed_and_utc_deterministic_rotating_canary():
    policy = load_module("daily_ai_policy_plan", POLICY_PATH)
    manifest = {
        "schema_version": 2,
        "specs": {},
        "daily_canaries": {
            "fixed": ["fixed-a.spec.ts"],
            "rotating": ["rotate-b.spec.ts", "rotate-a.spec.ts"],
        },
    }

    plan = policy.daily_plan(
        ["fixed-a.spec.ts", "rotate-a.spec.ts", "rotate-b.spec.ts"],
        date(2026, 8, 30),
        scheduled=True,
        record_mode=False,
        manifest=manifest,
    )

    assert plan.fixed == ("fixed-a.spec.ts",)
    assert plan.rotating == ("rotate-a.spec.ts",)
    assert plan == policy.daily_plan(
        ["fixed-a.spec.ts", "rotate-a.spec.ts", "rotate-b.spec.ts"],
        date(2026, 8, 30),
        scheduled=True,
        record_mode=False,
        manifest=manifest,
    )


# contract-test: direct surface=cli assertions=daily-ai-tests.real.fixed-plus-rotating,daily-ai-tests.validation.conditional-real-gate
def test_daily_plan_omits_absent_canaries_and_rejects_scheduled_record_mode():
    policy = load_module("daily_ai_policy_rejections", POLICY_PATH)
    manifest = {"schema_version": 2, "specs": {}, "daily_canaries": {"fixed": ["missing.spec.ts"], "rotating": []}}

    with pytest.raises(ValueError, match="requires at least one rotating"):
        policy.daily_plan([], date(2026, 8, 30), scheduled=True, record_mode=False, manifest=manifest)
    with pytest.raises(ValueError, match="Scheduled daily AI runs cannot use record mode"):
        policy.daily_plan([], date(2026, 8, 30), scheduled=True, record_mode=True, manifest=manifest)


# contract-test: direct surface=cli assertions=daily-ai-tests.real.fixed-plus-rotating,daily-ai-tests.validation.conditional-real-gate
def test_runner_daily_discovery_uses_policy_and_rejects_record_mode(monkeypatch, tmp_path):
    run_tests = load_module("daily_ai_runner", RUN_TESTS_PATH)
    spec_dir = tmp_path / "tests"
    spec_dir.mkdir()
    for name in (
        "ordinary-non-ai.spec.ts",
        "deep-research-real-inference.spec.ts",
        "daily-ai-fixed-canary.spec.ts",
        "daily-ai-rotating-canary.spec.ts",
    ):
        (spec_dir / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(run_tests, "SPEC_DIR", spec_dir)

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.spec = None
    orchestrator.core_journeys = False
    orchestrator.critical_journeys = False
    orchestrator.only_failed = False
    orchestrator.daily = True
    orchestrator.record_live_fixtures = False

    assert orchestrator._discover_specs() == [
        "ordinary-non-ai.spec.ts",
        "daily-ai-fixed-canary.spec.ts",
        "daily-ai-rotating-canary.spec.ts",
    ]
    orchestrator.record_live_fixtures = True
    with pytest.raises(ValueError, match="Scheduled daily AI runs cannot use record mode"):
        orchestrator._discover_specs()


def test_audit_rejects_stale_spec_file_and_command_references(monkeypatch, tmp_path):
    audit = load_module("daily_ai_audit_stale_refs", AUDIT_PATH)
    spec_path = tmp_path / "docs" / "specs" / "cost-safe-daily-ai-tests" / "spec.yml"
    scripts_dir = tmp_path / "scripts"
    spec_path.parent.mkdir(parents=True)
    scripts_dir.mkdir()
    (scripts_dir / "tests.py").write_text('sub.add_parser("run", help="Run tests")\n', encoding="utf-8")
    spec_path.write_text(
        """
tests:
  - id: T-STALE
    file: missing/file.py
    command: python3 scripts/tests.py cache refresh --spec missing.spec.ts
tasks:
  - id: TASK-STALE
    expected_files:
      - missing/expected.py
    ownership:
      files: [missing/owned.py]
      shared_files: []
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(audit, "SPEC_DIR", tmp_path / "frontend" / "apps" / "web_app" / "tests")
    monkeypatch.setattr(audit, "SPEC_PATH", spec_path)

    errors = audit._audit_spec_references()

    assert any("missing/file.py" in error for error in errors)
    assert any("unknown scripts/tests.py command 'cache'" in error for error in errors)
    assert any("missing/expected.py" in error for error in errors)
    assert any("missing/owned.py" in error for error in errors)


def test_audit_rejects_missing_raw_httpx_guard(monkeypatch, tmp_path):
    audit = load_module("daily_ai_audit_raw_http_guard", AUDIT_PATH)
    mock_context = tmp_path / "backend" / "shared" / "testing" / "mock_context.py"
    mock_context.parent.mkdir(parents=True)
    mock_context.write_text("def activate_mock_mode(): pass\n", encoding="utf-8")

    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(audit, "MOCK_CONTEXT_PATH", mock_context)

    assert audit._audit_raw_http_dispatch_guard() == [
        "raw httpx transport guard is incomplete in backend/shared/testing/mock_context.py"
    ]
