# backend/tests/test__technical_debt_helper.py
#
# Unit coverage for the weekly technical-debt OpenCode helper. The dry-run path
# verifies prompt assembly without spawning OpenCode, sending email, or writing
# nightly summaries.
# Architecture context: scripts/_technical_debt_helper.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _technical_debt_helper  # noqa: E402


def test_run_analysis_dry_run_renders_report_prompt(tmp_path, monkeypatch, capsys) -> None:
    """Dry-run mode should render report context and avoid spawning OpenCode."""

    report_dir = tmp_path / "logs" / "nightly-reports"
    report_dir.mkdir(parents=True)
    json_report = report_dir / "technical-debt.json"
    markdown_report = report_dir / "technical-debt.md"
    prompt = tmp_path / "prompt.md"
    json_report.write_text(
        '{"generated_at":"2026-06-05T00:00:00Z","head_sha":"abc123","summary":{"source_files_analyzed":1},"delta":{"has_previous":false},"top_hotspots_by_score":[],"churn_hotspots_6_months":[],"directory_rollup":[],"duplication_fingerprints":[]}',
        encoding="utf-8",
    )
    markdown_report.write_text("# Technical Debt\n", encoding="utf-8")
    prompt.write_text("Date {{DATE}} JSON {{JSON_REPORT_PATH}} MD {{MARKDOWN_REPORT_PATH}} {{REPORT_SUMMARY_JSON}} {{REPORT_MARKDOWN}}", encoding="utf-8")

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TODAY_DATE", "2026-06-05")
    monkeypatch.setenv("TECH_DEBT_JSON_REPORT", str(json_report))
    monkeypatch.setenv("TECH_DEBT_MARKDOWN_REPORT", str(markdown_report))
    monkeypatch.setenv("PROMPT_TEMPLATE_PATH", str(prompt))

    _technical_debt_helper.run_analysis()

    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert "logs/nightly-reports/technical-debt.json" in output
    assert "abc123" in output
    assert "# Technical Debt" in output
