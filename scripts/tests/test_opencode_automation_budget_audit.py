"""Tests for OpenCode automation safety audits.

Purpose: prevent permission-skipping automation from passing the audit with
dead-code marker strings instead of real approval checks or scoped risk notes.
Security: no OpenCode process is launched; tests only inspect temporary files.
Run: python3 -m pytest scripts/tests/test_opencode_automation_budget_audit.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_opencode_automation_budget.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_opencode_automation_budget", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def audit_temp_script(monkeypatch, tmp_path: Path, text: str):
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit, "PROMPTS_ROOT", tmp_path / "scripts" / "prompts")
    script = tmp_path / "automation.py"
    script.write_text(text, encoding="utf-8")
    return audit.audit_script(script)


def test_permission_skip_rejects_false_approval_marker(monkeypatch, tmp_path: Path) -> None:
    issues = audit_temp_script(
        monkeypatch,
        tmp_path,
        """
import subprocess
requires_human_approval = False
subprocess.run(["opencode", "run", "--dangerously-skip-permissions", "task"], timeout=30)
""",
    )

    assert any("human-approval guard" in issue.message for issue in issues)


def test_permission_skip_accepts_explicit_risk_classification(monkeypatch, tmp_path: Path) -> None:
    issues = audit_temp_script(
        monkeypatch,
        tmp_path,
        """
import subprocess
OPENCODE_AUTOMATION_RISK_CLASSIFICATION = "low-risk docs review; scoped prompt and timeout"
subprocess.run(["opencode", "run", "--dangerously-skip-permissions", "task"], timeout=30)
""",
    )

    assert issues == []


def test_repo_tests_are_not_treated_as_live_automation(monkeypatch, tmp_path: Path) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit, "PROMPTS_ROOT", tmp_path / "scripts" / "prompts")
    script = tmp_path / "scripts" / "tests" / "test_spawn_chat_opencode.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        'assert "opencode run --dangerously-skip-permissions" not in command\n',
        encoding="utf-8",
    )

    assert audit.audit_script(script) == []


def test_opencode_runtime_text_is_not_a_direct_invocation(monkeypatch, tmp_path: Path) -> None:
    issues = audit_temp_script(
        monkeypatch,
        tmp_path,
        '"""Reconstruct durable routing without depending on OpenCode runtime state."""\n',
    )

    assert issues == []


def test_permission_skip_accepts_runtime_human_approval_check(monkeypatch, tmp_path: Path) -> None:
    issues = audit_temp_script(
        monkeypatch,
        tmp_path,
        """
RISKY_TRIGGER_DOMAINS='auth payment billing encryption sync privacy legal migration websocket'
if [[ "$requires_human_approval" != "true" ]]; then
    exit 1
fi
timeout 1800 opencode run --dangerously-skip-permissions task
""",
    )

    assert issues == []


def test_retirement_audit_rejects_restored_launcher_and_registration(tmp_path):
    audit = load_audit_module()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "linear-poller.py").write_text("# accidentally restored launcher\n")
    (scripts / "linear-cron-setup.sh").write_text("systemctl --user enable linear-poller.service\n")
    issues = audit.audit_retired_automation(tmp_path)
    assert {issue.path for issue in issues} == {
        "scripts/linear-poller.py", "scripts/linear-cron-setup.sh",
    }


def test_retirement_audit_preserves_deterministic_scans_and_manual_tools(tmp_path):
    audit = load_audit_module()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "weekly-contract-audits.sh").write_text("python3 scripts/run_contract_audits.py\n")
    (scripts / "linear-cron-setup.sh").write_text("systemctl --user enable linear-archive.timer\n")
    (scripts / "sessions.py").write_text("# retained routing/deploy and manual chat tooling\n")
    assert audit.audit_retired_automation(tmp_path) == []


def test_retired_launchers_are_absent_from_repository():
    audit = load_audit_module()
    assert audit.audit_retired_automation(ROOT) == []


def load_collector(monkeypatch, name, reports, snapshots):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setitem(sys.modules, "security_scan_reporting", SimpleNamespace(
        report_scan=lambda **kwargs: reports.append(kwargs),
        ingest_snapshot=lambda **kwargs: snapshots.append(kwargs),
    ))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_dependabot_default_path_reports_without_launch_or_legacy_tracking(monkeypatch, tmp_path):
    import json
    reports = []
    helper = load_collector(monkeypatch, "_dependabot_helper", reports, [])
    monkeypatch.delenv("SECURITY_REPORTING_COLLECTION_ONLY", raising=False)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tmp_path / "tracking.json"))
    monkeypatch.setenv("ALERTS_JSON_FILE", str(tmp_path / "alerts.json"))
    monkeypatch.setattr(helper, "_current_commit", lambda _: "test-commit")
    (tmp_path / "alerts.json").write_text(json.dumps([{
        "number": 1, "dependency": {"package": {"name": "example", "ecosystem": "npm"}, "manifest_path": "pnpm-lock.yaml"},
        "security_advisory": {"ghsa_id": "GHSA-test-test-test", "severity": "high", "summary": "Test advisory"},
        "security_vulnerability": {"first_patched_version": {"identifier": "2.0.0"}},
    }]))
    helper.process_alerts()
    assert len(reports) == 1
    assert reports[0]["source"] == "dependabot"
    assert len(reports[0]["findings"]) == 1
    assert not (tmp_path / "tracking.json").exists()
    assert not hasattr(helper, "run_opencode_session")


def test_eu_default_path_keeps_coverage_and_never_dispatches(monkeypatch, tmp_path):
    reports = []
    helper = load_collector(monkeypatch, "_eu_vuln_helper", reports, [])
    monkeypatch.delenv("SECURITY_REPORTING_COLLECTION_ONLY", raising=False)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(helper, "_current_commit", lambda _: "test-commit")
    monkeypatch.setattr(helper, "_collect_all_dependencies", lambda _: [{"name": "example", "ecosystem": "npm", "version": "1.0.0"}])
    coverage = {"expected_and_completed_stages": {"osv_queries": [1, 1]}, "sanitized_failure_codes": []}
    monkeypatch.setattr(helper, "_query_osv_batch", lambda _: ([], coverage))
    finding = {"vuln_id": "TEST-1", "package": "example", "ecosystem": "npm", "severity": "high"}
    monkeypatch.setattr(helper, "_process_osv_results", lambda *_: ([finding], [finding]))
    helper.check_vulns()
    assert len(reports) == 1
    assert reports[0]["findings"] == [finding]
    assert reports[0]["coverage"]["expected_and_completed_stages"]["osv_queries"] == [1, 1]
    assert not (tmp_path / "tracking.json").exists()
    assert not hasattr(helper, "run_opencode_session")


def test_security_defaults_ingest_snapshots_without_creating_audits(monkeypatch, tmp_path):
    snapshots = []
    helper = load_collector(monkeypatch, "_security_helper", [], snapshots)
    monkeypatch.delenv("SECURITY_REPORTING_COLLECTION_ONLY", raising=False)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "true")
    helper.run_audit()
    helper.run_redteam()
    assert [item["source"] for item in snapshots] == ["security_audit", "redteam"]
    assert all(item["dry_run"] for item in snapshots)
    assert all(str(item["path"]).startswith(str(tmp_path)) for item in snapshots)
    assert not hasattr(helper, "run_opencode_session")


def test_retirement_audit_rejects_runtime_configuration(tmp_path):
    audit = load_audit_module()
    (tmp_path / "opencode.json").write_text("{}")
    assert any(issue.path == "opencode.json" for issue in audit.audit_retired_automation(tmp_path))
