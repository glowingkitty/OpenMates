# backend/tests/test_technical_debt_scan.py
#
# Unit coverage for the deterministic technical debt scanner. These tests focus
# on stable report math and Markdown output without walking the full repository
# or spawning OpenCode.
# Architecture context: scripts/technical_debt_scan.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import technical_debt_scan  # noqa: E402


def test_delta_reports_pattern_and_hotspot_changes() -> None:
    """Previous-run deltas should identify changed totals and new hotspots."""

    current = {
        "summary": {
            "source_files_analyzed": 11,
            "source_lines_analyzed": 1200,
            "pattern_totals": {"todo": 3, "suppression": 2},
        },
        "top_hotspots_by_score": [{"path": "new.py"}, {"path": "old.py"}],
    }
    previous = {
        "generated_at": "2026-06-01T00:00:00Z",
        "summary": {
            "source_files_analyzed": 10,
            "source_lines_analyzed": 1000,
            "pattern_totals": {"todo": 1, "broad_exception": 4},
        },
        "top_hotspots_by_score": [{"path": "old.py"}],
    }

    delta = technical_debt_scan._delta(current, previous)

    assert delta["has_previous"] is True
    assert delta["source_files_delta"] == 1
    assert delta["source_lines_delta"] == 200
    assert delta["pattern_deltas"] == {"broad_exception": -4, "suppression": 2, "todo": 2}
    assert delta["new_top_hotspots"] == ["new.py"]


def test_write_markdown_includes_deltas_and_hotspots(tmp_path) -> None:
    """Markdown report should surface the fields consumed by weekly review."""

    output = tmp_path / "technical-debt.md"
    report = {
        "generated_at": "2026-06-05T00:00:00Z",
        "head_sha": "abc123",
        "summary": {
            "source_files_analyzed": 2,
            "source_lines_analyzed": 300,
            "median_debt_score": 7,
            "pattern_totals": {"todo": 1},
        },
        "delta": {"has_previous": True, "source_files_delta": 1, "source_lines_delta": 50, "pattern_deltas": {"todo": 1}},
        "top_hotspots_by_score": [
            {
                "path": "frontend/example.svelte",
                "lines": 250,
                "score": 42,
                "complexity_signals": 12,
                "broad_exception": 2,
                "console_log": 3,
                "store_internal_import": 1,
                "suppression": 0,
            }
        ],
        "churn_hotspots_6_months": [["frontend/example.svelte", 5]],
        "duplication_fingerprints": [],
    }

    technical_debt_scan.write_markdown(report, output)

    markdown = output.read_text(encoding="utf-8")
    assert "Delta since previous run: +1 files, +50 lines" in markdown
    assert "`todo`: 1 (+1)" in markdown
    assert "`frontend/example.svelte`" in markdown
    assert "5 changes in 6 months" in markdown
