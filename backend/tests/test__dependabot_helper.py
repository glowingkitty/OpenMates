"""Test dev-branch Dependabot alert processing safeguards.

The host scanner may inspect default-branch GitHub metadata, but it must decide
against the current dev dependency graph and dry runs must remain side-effect
free. These tests protect unattended security-update scheduling.
"""

import json
from pathlib import Path

from scripts import _dependabot_helper as helper


# contract-test: infrastructure
def test_dry_run_does_not_persist_dispatch_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    alerts = tmp_path / "alerts.json"
    alerts.write_text(
        json.dumps(
            [
                {
                    "number": 1,
                    "dependency": {
                        "package": {"name": "example", "ecosystem": "npm"},
                        "manifest_path": "pnpm-lock.yaml",
                    },
                    "security_advisory": {
                        "ghsa_id": "GHSA-test-test-test",
                        "severity": "high",
                        "summary": "Test advisory",
                    },
                    "security_vulnerability": {
                        "first_patched_version": {"identifier": "2.0.0"}
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("{{DATE}}\n{{ALERT_SUMMARY}}", encoding="utf-8")
    tracking = tmp_path / "tracking.json"
    monkeypatch.setenv("ALERTS_JSON_FILE", str(alerts))
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tracking))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("PROMPT_TEMPLATE_PATH", str(prompt))
    monkeypatch.setattr(helper, "_check_ghsa_in_git", lambda *_: None)

    helper.process_alerts()

    assert not tracking.exists()
    assert "DRY RUN" in capsys.readouterr().out


# contract-test: infrastructure
def test_current_dev_lockfile_can_resolve_stale_default_branch_alert(
    tmp_path: Path,
) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n\npackages:\n\n  example@2.1.0:\n    resolution: {}\n\nsnapshots:\n",
        encoding="utf-8",
    )
    alert = {
        "package": "example",
        "ecosystem": "npm",
        "fixed_version": "2.0.0",
    }

    assert helper._alert_is_fixed_in_project(alert, str(tmp_path))
