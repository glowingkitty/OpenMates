# backend/tests/test_run_accessibility_weekly.py
#
# Unit coverage for the weekly accessibility audit notification wrapper.
# The tests exercise dry-run report generation without sending real email or
# requiring the local API server, Brevo credentials, Playwright, or Xcode.
# Architecture context: scripts/run_accessibility_weekly.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_accessibility_weekly  # noqa: E402


def _sample_report() -> dict:
    return {
        "generated_at": "2026-06-04T00:00:00+00:00",
        "summary": {
            "total_findings": 2,
            "counts_by_severity": {"critical": 0, "high": 1, "medium": 1, "low": 0, "info": 0},
            "counts_by_area": {"web": 2},
            "counts_by_category": {"example": 2},
            "counts_by_rule": [
                {
                    "id": "web.example.high",
                    "area": "web",
                    "category": "example",
                    "severity": "high",
                    "title": "High example",
                    "count": 1,
                    "example": "example.svelte:1",
                },
                {
                    "id": "web.example.medium",
                    "area": "web",
                    "category": "example",
                    "severity": "medium",
                    "title": "Medium example",
                    "count": 1,
                    "example": "example.svelte:2",
                },
            ],
        },
        "findings": [],
    }


def test_weekly_dry_run_writes_latest_and_dated_reports(tmp_path, monkeypatch, capsys) -> None:
    """Dry-run mode should write reports and never require email credentials."""

    monkeypatch.setattr(run_accessibility_weekly.accessibility_audit, "build_report", _sample_report)
    monkeypatch.setattr(sys, "argv", ["run_accessibility_weekly.py", "--dry-run", "--output-dir", str(tmp_path)])

    exit_code = run_accessibility_weekly.main()

    assert exit_code == 0
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "latest.md").exists()
    assert list(tmp_path.glob("weekly-*.json"))
    assert list(tmp_path.glob("weekly-*.md"))
    output = capsys.readouterr().out
    assert "Dry run: email not sent." in output
    assert "Weekly Accessibility Audit" in output


def test_internal_payload_maps_rule_groups_to_email_findings(tmp_path) -> None:
    """Internal email fallback should include rule groups as failed-test rows."""

    markdown_path = tmp_path / "weekly.md"
    markdown_path.write_text("report", encoding="utf-8")

    payload = run_accessibility_weekly._build_internal_summary_payload(
        report=_sample_report(),
        recipient="admin@example.com",
        subject="Weekly accessibility",
        git_sha="abc123",
        git_branch="dev",
        environment="development",
        duration_seconds=3,
        markdown_path=markdown_path,
    )

    assert payload["recipient_email"] == "admin@example.com"
    assert payload["subject_override"] == "Weekly accessibility"
    assert payload["failed"] == 2
    assert payload["failed_tests"][0]["suite"] == "accessibility-static-audit"
    assert "web.example.high" in payload["failed_tests"][0]["name"]
