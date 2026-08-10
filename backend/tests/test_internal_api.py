# contract-test-file: infrastructure
# backend/tests/test_internal_api.py
#
# Focused contracts for internal-only API task dispatch.
# These tests verify structured payload propagation without sending email or
# crossing the internal service-token boundary.

import asyncio

import pytest


def test_dispatch_test_summary_email_forwards_canonical_failure_groups(monkeypatch) -> None:
    try:
        from backend.core.api.app.routes import internal_api
        from backend.core.api.app.tasks import celery_config
    except ImportError as exc:
        pytest.skip(f"Backend dependencies not installed: {exc}")

    captured = {}

    class FakeCeleryApp:
        def send_task(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(celery_config, "app", FakeCeleryApp())
    payload = internal_api.TestRunSummaryEmailPayload(
        recipient_email="admin@example.test",
        run_id="2026-08-07T03:00:01Z",
        git_sha="e5c186d82",
        git_branch="dev",
        duration_seconds=120,
        total=2,
        passed=0,
        failed=2,
        skipped=0,
        not_started=0,
        suites=[],
        failed_tests=[],
        failure_groups=[{"title": "Playwright", "description": "Core chat"}],
    )

    result = asyncio.run(internal_api.dispatch_test_summary_email(payload, request=None))

    assert result == {"status": "dispatched"}
    assert captured["kwargs"]["failure_groups"] == [
        {"title": "Playwright", "description": "Core chat"}
    ]
