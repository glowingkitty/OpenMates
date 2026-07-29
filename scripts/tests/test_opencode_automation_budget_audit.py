"""Tests for OpenCode automation safety audits.

Purpose: prevent permission-skipping automation from passing the audit with
dead-code marker strings instead of real approval checks or scoped risk notes.
Security: no OpenCode process is launched; tests only inspect temporary files.
Run: python3 -m pytest scripts/tests/test_opencode_automation_budget_audit.py.
"""

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
