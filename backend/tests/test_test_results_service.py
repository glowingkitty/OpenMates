#!/usr/bin/env python3
"""
Regression tests for the status-page test results service.

The status API should consume Directus-backed current test state rather than
requiring local JSON files to exist inside the API container.
"""

from __future__ import annotations

import importlib


def test_latest_run_detail_uses_directus_current_state_without_json(tmp_path, monkeypatch):
    service = importlib.import_module("backend.core.api.app.services.test_results_service")
    service._cache.clear()
    service._cache_timestamps.clear()
    monkeypatch.setattr(service, "TEST_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_load_directus_current_state", lambda: {
        "latest_run_id": "directus-run-1",
        "latest_git_sha": "abc123",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "tests": {
            "playwright::chat-flow.spec.ts": {
                "suite": "playwright",
                "test": "chat-flow.spec.ts",
                "status": "failed",
                "duration_seconds": 3,
                "error": "Locator failed",
                "run_id": "directus-run-1",
            }
        },
    })

    detail = service.get_latest_run_detail()

    assert detail is not None
    assert detail["run_id"] == "directus-run-1"
    assert detail["summary"]["failed"] == 1
    assert detail["suites"]["playwright"]["tests"][0]["file"] == "chat-flow.spec.ts"


def test_latest_run_summary_uses_directus_current_state_without_json(tmp_path, monkeypatch):
    service = importlib.import_module("backend.core.api.app.services.test_results_service")
    service._cache.clear()
    service._cache_timestamps.clear()
    monkeypatch.setattr(service, "TEST_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_load_directus_current_state", lambda: {
        "latest_run_id": "directus-run-1",
        "latest_git_sha": "abc123",
        "summary": {"total": 2, "passed": 1, "failed": 1, "skipped": 0},
        "tests": {
            "playwright::chat-flow.spec.ts": {"suite": "playwright", "test": "chat-flow.spec.ts", "status": "failed"},
            "pytest::backend/tests/test_example.py": {"suite": "pytest", "test": "backend/tests/test_example.py", "status": "passed"},
        },
    })

    summary = service.get_latest_run_summary()

    assert summary is not None
    assert summary["overall_status"] == "failing"
    assert {suite["name"] for suite in summary["suites"]} == {"playwright", "pytest"}
