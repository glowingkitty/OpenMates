"""Tests for the unattended failed-test auto-fix controller.

These tests exercise the controller logic without spawning OpenCode, posting to
Discord, running Playwright, or deploying. The controller lives under scripts/
because it is operational glue, but regressions there can stop nightly test
automation from recovering independently.
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import auto_fix_failed_tests as controller  # noqa: E402


def test_process_group_verifies_when_opencode_omits_summary_after_success(monkeypatch, tmp_path):
    """A successful OpenCode run without summary JSON should still verify safely."""
    group = controller.FixGroup(
        id="g01-test",
        suite="playwright",
        tests=[{"suite": "playwright", "file": "a11y-pages.spec.ts", "status": "failed"}],
        verify_command=["python3", "scripts/tests.py", "run", "--spec", "a11y-pages.spec.ts"],
    )
    args = Namespace(
        dry_run=False,
        max_attempts_per_group=1,
        timeout_seconds=30,
        verify_timeout_seconds=30,
        deploy_timeout_seconds=30,
        max_changed_files=5,
        max_diff_lines=200,
        no_deploy=True,
    )
    missing_summary_path = tmp_path / "summary-attempt-1.json"
    output_path = tmp_path / "opencode-output-attempt-1.jsonl"
    output_path.write_text('{"type":"text","part":{"text":"Ready for verification."}}\n')

    monkeypatch.setattr(controller, "start_controller_session", lambda group: "sess1")
    monkeypatch.setattr(controller, "end_session", lambda session_id: None)
    monkeypatch.setattr(
        controller,
        "run_opencode",
        lambda *args, **kwargs: (0, str(output_path), missing_summary_path, "opencode1", ""),
    )
    changed_file_snapshots = iter([[], ["frontend/packages/ui/src/components/Header.svelte"]])
    monkeypatch.setattr(controller, "changed_files", lambda: next(changed_file_snapshots))
    monkeypatch.setattr(controller, "diff_line_count", lambda files: 4)
    monkeypatch.setattr(controller, "track_session_files", lambda session_id, files: None)
    monkeypatch.setattr(controller, "run_verification", lambda group, timeout: ("passed", 0, "ok"))
    monkeypatch.setattr(controller, "post_discord", lambda summary, color=0x3B82F6: True)

    summary = controller.process_group(group, "run1", args)

    assert summary["status"] == "fixed"
    assert summary["scope_classification"] == "minor"
    assert summary["verification_result"] == "passed"
    assert summary["commit_sha"] == "not deployed (--no-deploy)"
    assert summary["changed_files"] == ["frontend/packages/ui/src/components/Header.svelte"]
    assert summary["summary_recovered"] is True
