# backend/tests/test_rest_api_status.py
#
# Integration tests for the unified status page API endpoints:
#   - GET /v1/status (summary)
#   - GET /v1/status?section=... (filtered)
#   - GET /v1/status?detail=full (admin-only, 403 without auth)
#   - GET /v1/status/health?group=... (service group detail)
#   - GET /v1/status/tests (test detail)
#   - GET /v1/status/incidents (incident history)
#
# All endpoints are public (no API key required) for summary access.
# detail=full requires admin JWT and returns 403 without it.
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_status.py

import os

import httpx
import pytest

from backend.tests.conftest import API_BASE_URL, log_response

# Use local API when available (for testing before remote deployment)
STATUS_API_BASE_URL = os.getenv("STATUS_TEST_API_URL", API_BASE_URL)


def _public_client() -> httpx.Client:
    """Create an unauthenticated httpx client for public status endpoints."""
    return httpx.Client(
        base_url=STATUS_API_BASE_URL,
        timeout=30.0,
        event_hooks={"response": [log_response]},
    )


# ─── GET /v1/status (summary) ───────────────────────────────────────────────


@pytest.mark.integration
def test_status_summary_returns_200():
    """GET /v1/status returns 200 with summary data."""
    with _public_client() as client:
        response = client.get("/v1/status")
        assert response.status_code == 200, f"Status failed: {response.text}"
        data = response.json()

        # Required top-level fields
        assert "overall_status" in data
        assert data["overall_status"] in ("operational", "degraded", "down", "unknown")
        assert "last_updated" in data
        assert "is_admin" in data
        assert data["is_admin"] is False  # No auth = not admin


@pytest.mark.integration
def test_status_summary_includes_health_groups():
    """Summary response includes health groups with status colors."""
    with _public_client() as client:
        data = client.get("/v1/status").json()

        assert "health" in data
        groups = data["health"]["groups"]
        assert isinstance(groups, list)
        assert len(groups) > 0

        for group in groups:
            assert "group_name" in group
            assert "display_name" in group
            assert "status" in group
            assert "service_count" in group
            assert group["status"] in ("operational", "degraded", "down", "unknown")
            # Summary should NOT include individual services
            assert "services" not in group


@pytest.mark.integration
def test_status_summary_includes_tests():
    """Summary response includes test suite summaries and trend."""
    with _public_client() as client:
        data = client.get("/v1/status").json()

        assert "tests" in data
        tests = data["tests"]
        assert "overall_status" in tests
        assert tests["overall_status"] in ("passing", "failing", "unknown")
        assert "suites" in tests
        assert isinstance(tests["suites"], list)

        # Each suite has counts, no individual test rows
        for suite in tests["suites"]:
            assert "name" in suite
            assert "status" in suite
            assert "total" in suite
            assert "passed" in suite
            assert "failed" in suite

        assert "trend" in tests
        assert isinstance(tests["trend"], list)


@pytest.mark.integration
def test_status_summary_includes_timeline():
    """Summary response includes 90-day timeline buckets."""
    with _public_client() as client:
        data = client.get("/v1/status").json()

        assert "timeline" in data
        timeline = data["timeline"]
        assert timeline["period_days"] == 90
        assert "buckets" in timeline
        assert isinstance(timeline["buckets"], list)
        assert len(timeline["buckets"]) > 0

        for bucket in timeline["buckets"]:
            assert "start" in bucket
            assert "end" in bucket
            assert "status" in bucket
            assert bucket["status"] in ("operational", "degraded", "down", "unknown")


@pytest.mark.integration
def test_status_summary_includes_incidents():
    """Summary response includes incident count."""
    with _public_client() as client:
        data = client.get("/v1/status").json()

        assert "incidents" in data
        assert "total_last_30d" in data["incidents"]
        assert isinstance(data["incidents"]["total_last_30d"], int)


# ─── Section filtering ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_status_section_filter_health_only():
    """?section=health returns only health data (plus overall_status)."""
    with _public_client() as client:
        data = client.get("/v1/status?section=health").json()

        assert "health" in data
        assert "overall_status" in data
        assert "tests" not in data
        assert "timeline" not in data
        assert "incidents" not in data


@pytest.mark.integration
def test_status_section_filter_tests_only():
    """?section=tests returns only test data."""
    with _public_client() as client:
        data = client.get("/v1/status?section=tests").json()

        assert "tests" in data
        assert "health" not in data
        assert "timeline" not in data
        assert "incidents" not in data


@pytest.mark.integration
def test_status_section_filter_multiple():
    """?section=health,tests returns both."""
    with _public_client() as client:
        data = client.get("/v1/status?section=health,tests").json()

        assert "health" in data
        assert "tests" in data
        assert "timeline" not in data
        assert "incidents" not in data


@pytest.mark.integration
def test_status_section_filter_invalid():
    """?section=invalid returns 400."""
    with _public_client() as client:
        response = client.get("/v1/status?section=invalid")
        assert response.status_code == 400


# ─── detail=full (admin auth gating) ─────────────────────────────────────────


@pytest.mark.integration
def test_status_detail_full_requires_admin():
    """?detail=full without admin auth returns 403."""
    with _public_client() as client:
        response = client.get("/v1/status?detail=full")
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()


@pytest.mark.integration
def test_status_detail_invalid_value():
    """?detail=invalid returns 400."""
    with _public_client() as client:
        response = client.get("/v1/status?detail=invalid")
        assert response.status_code == 400


# ─── GET /v1/status/health?group=... ─────────────────────────────────────────


@pytest.mark.integration
def test_status_health_detail_returns_services():
    """Health detail endpoint returns individual services for a group."""
    with _public_client() as client:
        # First get available groups
        summary = client.get("/v1/status?section=health").json()
        groups = summary["health"]["groups"]
        assert len(groups) > 0

        group_name = groups[0]["group_name"]
        response = client.get(f"/v1/status/health?group={group_name}")
        assert response.status_code == 200

        data = response.json()
        assert data["group_name"] == group_name
        assert "services" in data
        assert isinstance(data["services"], list)
        assert len(data["services"]) > 0

        # Non-admin: services should not have error details
        for service in data["services"]:
            assert "id" in service
            assert "name" in service
            assert "status" in service
            assert "error_message" not in service
            assert "response_time_ms" not in service


@pytest.mark.integration
def test_status_health_detail_invalid_group():
    """Health detail with invalid group returns 404."""
    with _public_client() as client:
        response = client.get("/v1/status/health?group=nonexistent_group")
        assert response.status_code == 404


@pytest.mark.integration
def test_status_health_detail_missing_group():
    """Health detail without group param returns 422 (missing required param)."""
    with _public_client() as client:
        response = client.get("/v1/status/health")
        assert response.status_code == 422  # FastAPI validation error


@pytest.mark.integration
def test_status_health_detail_full_requires_admin():
    """Health detail with detail=full requires admin auth."""
    with _public_client() as client:
        response = client.get("/v1/status/health?group=apps&detail=full")
        assert response.status_code == 403


# ─── GET /v1/status/tests ────────────────────────────────────────────────────


@pytest.mark.integration
def test_status_tests_detail():
    """Tests detail endpoint returns test data."""
    with _public_client() as client:
        response = client.get("/v1/status/tests")
        assert response.status_code == 200

        data = response.json()
        assert "suites" in data

        # Non-admin: errors should be stripped from tests
        for suite_name, suite_data in data.get("suites", {}).items():
            for test in suite_data.get("tests", []):
                assert "name" in test
                assert "status" in test
                # Error field should not be present for non-admin
                assert "error" not in test or test["error"] is None


@pytest.mark.integration
def test_status_tests_suite_filter():
    """Tests detail with suite filter returns only that suite."""
    with _public_client() as client:
        response = client.get("/v1/status/tests?suite=playwright")
        assert response.status_code == 200

        data = response.json()
        suites = data.get("suites", {})
        # Should only contain the requested suite (or be empty if no data)
        for suite_name in suites:
            assert suite_name == "playwright"


@pytest.mark.integration
def test_status_tests_detail_full_requires_admin():
    """Tests detail with detail=full requires admin auth."""
    with _public_client() as client:
        response = client.get("/v1/status/tests?detail=full")
        assert response.status_code == 403


# ─── GET /v1/status/incidents ────────────────────────────────────────────────


@pytest.mark.integration
def test_status_incidents_detail():
    """Incidents endpoint returns event data."""
    with _public_client() as client:
        response = client.get("/v1/status/incidents")
        assert response.status_code == 200

        data = response.json()
        assert "since_days" in data
        assert "total_incidents" in data
        assert "events" in data
        assert isinstance(data["events"], list)

        # Non-admin: no error messages or downtime details
        assert data.get("total_downtime_seconds") is None
        assert data.get("services") is None


@pytest.mark.integration
def test_status_incidents_since_days():
    """Incidents endpoint accepts since_days parameter."""
    with _public_client() as client:
        response = client.get("/v1/status/incidents?since_days=7")
        assert response.status_code == 200
        assert response.json()["since_days"] == 7


@pytest.mark.integration
def test_status_incidents_since_days_invalid():
    """Incidents endpoint rejects invalid since_days values."""
    with _public_client() as client:
        response = client.get("/v1/status/incidents?since_days=0")
        assert response.status_code == 422  # FastAPI validation (ge=1)

        response = client.get("/v1/status/incidents?since_days=100")
        assert response.status_code == 422  # FastAPI validation (le=90)


@pytest.mark.integration
def test_status_incidents_detail_full_requires_admin():
    """Incidents detail with detail=full requires admin auth."""
    with _public_client() as client:
        response = client.get("/v1/status/incidents?detail=full")
        assert response.status_code == 403
