# contract-test-file: tooling
"""Public daily test results expose counts without raw runner diagnostics."""

import json
from datetime import date

from backend.core.api.app.routes import status_routes


def test_status_prefers_canonical_nightly_result_mount(tmp_path, monkeypatch) -> None:
    canonical = tmp_path / "canonical"
    runtime = tmp_path / "runtime"
    canonical.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(status_routes, "TEST_RESULTS_PATHS", [canonical, runtime])
    assert status_routes._find_test_results_dir() == canonical


def test_daily_result_loads_exact_date_and_projects_public_fields(tmp_path, monkeypatch) -> None:
    result_dir = tmp_path / "daily-runs/results"
    result_dir.mkdir(parents=True)
    result = {
        "schema_version": 1, "date": "2026-09-28", "status": "blocked",
        "finalization": "final", "source_commit": "a" * 40,
        "areas": {"unit": {"executed": 6772, "passed": 6600, "failed": 172, "skipped": 5}},
        "apple_e2e": {"status": "not_scheduled", "counts": {"executed": 0}},
        "signup": {"executed": [], "held": [], "live_email": {"status": "failed"}},
        "case_counts": [{"area": "pytest", "failed": 154}],
        "selection_error": "private runner detail",
        "run_links": ["https://github.com/glowingkitty/OpenMates/actions/runs/123", "https://untrusted.example/"],
    }
    (result_dir / "2026-09-28.json").write_text(json.dumps(result))
    monkeypatch.setattr(status_routes, "_find_test_results_dir", lambda: tmp_path)
    loaded = status_routes._daily_result(date(2026, 9, 28))
    assert loaded is not None
    public = status_routes._public_daily_result(loaded)
    assert public["areas"]["unit"]["executed"] == 6772
    assert public["failure_areas"] == [{"area": "pytest", "failed": 154}]
    assert "selection_error" not in public
    assert len(public["run_links"]) == 1
    html = status_routes._daily_result_html(public)
    assert "6772" in html and "Native Apple E2E" in html and "BLOCKED" in html
