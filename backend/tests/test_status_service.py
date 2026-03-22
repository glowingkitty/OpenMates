# backend/tests/test_status_service.py
#
# Unit tests for the test_results_service and status_aggregator modules.
# These are fast, no external dependencies — just test data parsing logic.
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_status_service.py

import json
from datetime import date, timedelta

import pytest

from backend.core.api.app.services.test_results_service import (
    _read_json_file,
    _cache,
    _cache_timestamps,
    categorize_test,
    get_daily_trend,
    get_categorized_test_summary,
    get_flaky_tests,
    get_latest_run_detail,
    get_latest_run_summary,
    get_per_suite_daily_history,
    get_per_test_history,
)

from backend.core.api.app.services.status_aggregator import (
    _compute_group_status,
    _get_external_group,
    _normalize_status,
    build_health_groups,
    build_health_groups_summary,
    compute_overall_status,
    filter_public_status_health_data,
    strip_admin_fields_from_tests,
    strip_admin_fields_from_incidents,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-memory cache before each test."""
    _cache.clear()
    _cache_timestamps.clear()
    yield
    _cache.clear()
    _cache_timestamps.clear()


SAMPLE_RUN = {
    "run_id": "2026-03-22T03:00:00Z",
    "git_sha": "abc1234",
    "git_branch": "dev",
    "duration_seconds": 300.0,
    "summary": {"total": 10, "passed": 8, "failed": 2, "skipped": 0},
    "suites": {
        "playwright": {
            "status": "failed",
            "tests": [
                {"name": "test-a.spec.ts", "file": "test-a.spec.ts", "status": "passed", "duration_seconds": 5.0},
                {"name": "test-b.spec.ts", "file": "test-b.spec.ts", "status": "failed", "duration_seconds": 10.0, "error": "Timeout exceeded"},
            ],
        },
        "vitest": {
            "status": "passed",
            "tests": [
                {"name": "store.test.ts", "file": "store.test.ts", "status": "passed", "duration_seconds": 0.5},
            ],
        },
    },
}


def _iso_day(offset_days: int = 0) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


def _write_daily_run(tmp_path, offset_days: int, payload: dict) -> None:
    day = _iso_day(offset_days)
    run_file = tmp_path / f"daily-run-{day}.json"
    run_file.write_text(json.dumps(payload))


# ─── test_results_service unit tests ─────────────────────────────────────────


class TestReadJsonFile:
    def test_reads_valid_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        result = _read_json_file(str(f))
        assert result == {"key": "value"}

    def test_returns_none_for_missing_file(self):
        result = _read_json_file("/nonexistent/path.json")
        assert result is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        result = _read_json_file(str(f))
        assert result is None


class TestGetLatestRunSummary:
    def test_returns_summary_without_individual_tests(self, tmp_path, monkeypatch):
        # Write sample run data
        run_file = tmp_path / "last-run.json"
        run_file.write_text(json.dumps(SAMPLE_RUN))
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        result = get_latest_run_summary()
        assert result is not None
        assert result["overall_status"] == "failing"
        assert result["latest_run"]["git_sha"] == "abc1234"
        assert result["latest_run"]["summary"]["total"] == 10

        # Suites should have counts but no individual test rows
        for suite in result["suites"]:
            assert "name" in suite
            assert "total" in suite
            assert "passed" in suite
            assert "failed" in suite

    def test_returns_none_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )
        result = get_latest_run_summary()
        assert result is None


class TestGetLatestRunDetail:
    def test_returns_individual_tests(self, tmp_path, monkeypatch):
        run_file = tmp_path / "last-run.json"
        run_file.write_text(json.dumps(SAMPLE_RUN))
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        result = get_latest_run_detail()
        assert result is not None
        assert "suites" in result
        pw_tests = result["suites"]["playwright"]["tests"]
        assert len(pw_tests) == 2
        assert pw_tests[1]["error"] == "Timeout exceeded"

    def test_filters_by_suite(self, tmp_path, monkeypatch):
        run_file = tmp_path / "last-run.json"
        run_file.write_text(json.dumps(SAMPLE_RUN))
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        result = get_latest_run_detail(suite_name="vitest")
        assert result is not None
        assert "vitest" in result["suites"]
        assert "playwright" not in result["suites"]


class TestGetDailyTrend:
    def test_reads_daily_run_files(self, tmp_path, monkeypatch):
        _write_daily_run(tmp_path, -2, {
            "run_id": f"{_iso_day(-2)}T03:00:00Z",
            "summary": {"total": 10, "passed": 8, "failed": 2, "skipped": 0},
        })
        _write_daily_run(tmp_path, -1, {
            "run_id": f"{_iso_day(-1)}T03:00:00Z",
            "summary": {"total": 11, "passed": 9, "failed": 2, "skipped": 0},
        })
        _write_daily_run(tmp_path, 0, {
            "run_id": f"{_iso_day(0)}T03:00:00Z",
            "summary": {"total": 12, "passed": 10, "failed": 2, "skipped": 0},
        })
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        result = get_daily_trend(days=3)
        assert len(result) == 3
        assert result[0]["date"] == _iso_day(-2)
        assert result[2]["date"] == _iso_day(0)
        assert result[2]["run_at"] == f"{_iso_day(0)}T03:00:00Z"
        assert result[2]["has_run"] is True

    def test_includes_placeholder_for_missing_days(self, tmp_path, monkeypatch):
        _write_daily_run(tmp_path, 0, {
            "run_id": f"{_iso_day(0)}T03:00:00Z",
            "summary": {"total": 12, "passed": 10, "failed": 2, "skipped": 0},
        })
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        result = get_daily_trend(days=2)
        assert len(result) == 2
        assert result[0]["date"] == _iso_day(-1)
        assert result[0]["has_run"] is False
        assert result[0]["run_at"] is None
        assert result[1]["has_run"] is True

    def test_returns_empty_list_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )
        result = get_daily_trend(days=2)
        assert len(result) == 2
        assert all(entry["has_run"] is False for entry in result)


class TestPerSuiteAndPerTestHistory:
    def test_fills_missing_suite_and_test_days(self, tmp_path, monkeypatch):
        run_file = tmp_path / "last-run.json"
        run_file.write_text(json.dumps(SAMPLE_RUN))
        _write_daily_run(tmp_path, 0, {
            "run_id": f"{_iso_day(0)}T03:00:00Z",
            "suites": {
                "playwright": {
                    "tests": [
                        {"name": "test-a.spec.ts", "file": "test-a.spec.ts", "status": "passed"},
                        {"name": "test-b.spec.ts", "file": "test-b.spec.ts", "status": "failed"},
                    ]
                }
            }
        })
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        suite_history = get_per_suite_daily_history(days=2)
        assert len(suite_history["playwright"]) == 2
        assert suite_history["playwright"][0]["has_run"] is False
        assert suite_history["playwright"][1]["has_run"] is True
        assert suite_history["playwright"][1]["run_at"] == f"{_iso_day(0)}T03:00:00Z"

        test_history = get_per_test_history(days=2)
        assert len(test_history["test-a.spec.ts"]) == 2
        assert test_history["test-a.spec.ts"][0]["status"] == "not_run"
        assert test_history["test-a.spec.ts"][1]["status"] == "passed"


class TestCategorizedSummary:
    def test_category_history_weights_not_run_lighter_than_failures(self, tmp_path, monkeypatch):
        last_run = {
            "run_id": f"{_iso_day(0)}T13:15:25Z",
            "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
            "suites": {
                "playwright": {
                    "tests": [
                        {"name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed"},
                        {"name": "chat-search-flow.spec.ts", "file": "chat-search-flow.spec.ts", "status": "passed"},
                    ]
                }
            }
        }
        (tmp_path / "last-run.json").write_text(json.dumps(last_run))
        _write_daily_run(tmp_path, 0, {
            "run_id": f"{_iso_day(0)}T13:15:25Z",
            "suites": {
                "playwright": {
                    "tests": [
                        {"name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed"},
                    ]
                }
            }
        })
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        summary = get_categorized_test_summary(is_admin=True)
        chat_history = summary["categories"]["Chat"]["history"]
        assert len(chat_history) == 30
        assert chat_history[-1]["date"] == _iso_day(0)
        assert chat_history[-1]["passed"] == 1
        assert chat_history[-1]["not_run"] == 1
        assert chat_history[-1]["has_run"] is True
        assert chat_history[-1]["tone"] == 75
        assert chat_history[-1]["run_at"] == f"{_iso_day(0)}T13:15:25Z"
        assert chat_history[-2]["has_run"] is False
        assert chat_history[-2]["tone"] is None

    def test_categories_include_all_suites(self, tmp_path, monkeypatch):
        """All suites are categorized — playwright by spec name, vitest/pytest by path."""
        last_run = {
            "run_id": f"{_iso_day(0)}T13:15:25Z",
            "summary": {"total": 3, "passed": 2, "failed": 1, "skipped": 0},
            "suites": {
                "playwright": {
                    "tests": [
                        {"name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed"},
                    ]
                },
                "vitest": {
                    "tests": [
                        {"name": "statusPage.test.ts", "file": "statusPage.test.ts", "status": "failed"},
                        {"name": "stores/store.test.ts", "file": "stores/store.test.ts", "status": "passed"},
                    ]
                },
            }
        }
        (tmp_path / "last-run.json").write_text(json.dumps(last_run))
        _write_daily_run(tmp_path, 0, last_run)
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        summary = get_categorized_test_summary(is_admin=True)

        # Playwright categories use plain names
        assert "Chat" in summary["categories"]
        assert summary["categories"]["Chat"]["total"] == 1
        assert summary["categories"]["Chat"]["suite"] == "playwright"

        # Vitest categories are prefixed with "vitest:"
        assert "vitest:Stores" in summary["categories"]
        assert summary["categories"]["vitest:Stores"]["total"] == 1
        assert summary["categories"]["vitest:Stores"]["display_name"] == "Stores"

        # Uncategorized vitest tests go to "vitest:Other"
        assert "vitest:Other" in summary["categories"]
        assert summary["categories"]["vitest:Other"]["total"] == 1

        assert summary["suites"]["vitest"]["total"] == 2


class TestGetFlakyTests:
    def test_reads_flaky_history(self, tmp_path, monkeypatch):
        f = tmp_path / "flaky-history.json"
        f.write_text(json.dumps({
            "test-a.spec.ts": {"flaky_count": 3, "total_runs": 10, "last_flaky": "2026-03-22"},
            "test-b.spec.ts": {"flaky_count": 1, "total_runs": 5},
        }))
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )

        result = get_flaky_tests()
        assert len(result) == 2
        # Sorted by flaky_count descending
        assert result[0]["name"] == "test-a.spec.ts"
        assert result[0]["flaky_count"] == 3

    def test_returns_empty_list_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.core.api.app.services.test_results_service.TEST_RESULTS_DIR",
            str(tmp_path),
        )
        result = get_flaky_tests()
        assert result == []


# ─── status_aggregator unit tests ────────────────────────────────────────────


class TestNormalizeStatus:
    def test_healthy_to_operational(self):
        assert _normalize_status("healthy") == "operational"

    def test_unhealthy_to_down(self):
        assert _normalize_status("unhealthy") == "down"

    def test_degraded_stays(self):
        assert _normalize_status("degraded") == "degraded"

    def test_unknown_input(self):
        assert _normalize_status("bogus") == "unknown"


class TestGetExternalGroup:
    def test_stripe_is_payment(self):
        assert _get_external_group("stripe") == "payment"

    def test_brevo_is_email(self):
        assert _get_external_group("brevo") == "email"

    def test_sightengine_is_moderation(self):
        assert _get_external_group("sightengine") == "content_moderation"

    def test_brave_is_search(self):
        assert _get_external_group("brave_search") == "search_and_data"

    def test_unknown_is_infrastructure(self):
        assert _get_external_group("unknown_service") == "infrastructure"


class TestComputeGroupStatus:
    def test_all_operational(self):
        services = [{"status": "operational"}, {"status": "operational"}]
        assert _compute_group_status(services) == "operational"

    def test_any_down(self):
        services = [{"status": "operational"}, {"status": "down"}]
        assert _compute_group_status(services) == "down"

    def test_degraded_without_down(self):
        services = [{"status": "operational"}, {"status": "degraded"}]
        assert _compute_group_status(services) == "degraded"

    def test_empty(self):
        assert _compute_group_status([]) == "unknown"


class TestComputeOverallStatus:
    def test_all_healthy(self):
        data = {"providers": {"p1": {"status": "healthy"}}, "apps": {}, "external_services": {}}
        assert compute_overall_status(data) == "operational"

    def test_some_unhealthy(self):
        data = {
            "providers": {"p1": {"status": "healthy"}, "p2": {"status": "unhealthy"}},
            "apps": {},
            "external_services": {},
        }
        assert compute_overall_status(data) == "degraded"

    def test_all_unhealthy(self):
        data = {"providers": {"p1": {"status": "unhealthy"}}, "apps": {}, "external_services": {}}
        assert compute_overall_status(data) == "down"

    def test_empty(self):
        data = {"providers": {}, "apps": {}, "external_services": {}}
        assert compute_overall_status(data) == "unknown"


class TestBuildHealthGroups:
    def test_non_admin_includes_public_services_and_timelines(self):
        health_data = {
            "providers": {"openai": {"status": "healthy", "last_error": "test error"}},
            "apps": {},
            "external_services": {},
        }
        groups = build_health_groups(health_data, {"provider/openai": [{"date": _iso_day(0), "status": "operational"}]}, is_admin=False)
        assert len(groups) == 1
        assert groups[0]["group_name"] == "ai_providers"
        assert "services" in groups[0]
        assert groups[0]["services"][0]["timeline_30d"][0]["status"] == "operational"

    def test_admin_includes_services_with_errors(self):
        health_data = {
            "providers": {"openai": {"status": "unhealthy", "last_error": "timeout", "last_check": 123}},
            "apps": {},
            "external_services": {},
        }
        groups = build_health_groups(health_data, {}, is_admin=True)
        assert "services" in groups[0]
        assert groups[0]["services"][0]["error_message"] == "timeout"


class TestBuildHealthGroupsSummary:
    def test_returns_groups_without_services(self):
        health_data = {
            "providers": {"openai": {"status": "healthy"}},
            "apps": {"web": {"status": "healthy"}},
            "external_services": {"stripe": {"status": "healthy"}},
        }
        groups = build_health_groups_summary(health_data, {})
        for group in groups:
            assert "group_name" in group
            assert "display_name" in group
            assert "status" in group
            assert "service_count" in group
            assert "timeline_30d" in group
            # Summary should NOT include services[]
            assert "services" not in group

    def test_computes_worst_status(self):
        health_data = {
            "providers": {
                "openai": {"status": "healthy"},
                "anthropic": {"status": "unhealthy"},
            },
            "apps": {},
            "external_services": {},
        }
        groups = build_health_groups_summary(health_data, {})
        ai_group = next(g for g in groups if g["group_name"] == "ai_providers")
        assert ai_group["status"] == "down"
        assert ai_group["service_count"] == 2


class TestCategorizeTestMultiSuite:
    def test_playwright_categorization(self):
        assert categorize_test("chat-flow.spec.ts", "playwright") == "Chat"
        assert categorize_test("signup.spec.ts", "playwright") == "Auth & Signup"
        assert categorize_test("unknown.spec.ts", "playwright") == "Other"

    def test_vitest_categorization(self):
        assert categorize_test("components/Button.test.ts", "vitest") == "Components"
        assert categorize_test("stores/auth.test.ts", "vitest") == "Stores"
        assert categorize_test("random.test.ts", "vitest") == "Other"

    def test_pytest_categorization(self):
        assert categorize_test("test_rest_api_status.py", "pytest_unit") == "API"
        assert categorize_test("test_model_response.py", "pytest_unit") == "AI & Models"
        assert categorize_test("test_random.py", "pytest_unit") == "Other"


class TestFilterPublicStatusHealthData:
    def test_filters_protonmail_from_public_status_overview(self):
        health_data = {
            "providers": {
                "openai": {"status": "healthy"},
                "protonmail": {"status": "unhealthy"},
            },
            "apps": {},
            "external_services": {},
        }

        filtered = filter_public_status_health_data(health_data)

        assert "openai" in filtered["providers"]
        assert "protonmail" not in filtered["providers"]


class TestStripAdminFieldsFromTests:
    def test_strips_error_from_test_rows(self):
        data = {
            "suites": {
                "playwright": {
                    "tests": [
                        {"name": "test-a", "file": "a.ts", "status": "failed", "duration_seconds": 1.0, "error": "secret error"},
                    ]
                }
            }
        }
        result = strip_admin_fields_from_tests(data)
        test = result["suites"]["playwright"]["tests"][0]
        assert "error" not in test
        assert test["name"] == "test-a"
        assert test["status"] == "failed"

    def test_strips_error_from_flaky_tests(self):
        data = {
            "flaky_tests": [
                {"name": "test-a", "flaky_count": 3, "total_runs": 10, "last_flaky": "2026-03-22", "error": "secret"},
            ]
        }
        result = strip_admin_fields_from_tests(data)
        assert "error" not in result["flaky_tests"][0]


class TestStripAdminFieldsFromIncidents:
    def test_strips_error_and_duration(self):
        events = [
            {
                "service_type": "provider",
                "service_id": "openai",
                "previous_status": "healthy",
                "new_status": "unhealthy",
                "created_at": "2026-03-22T00:00:00Z",
                "error_message": "connection refused",
                "duration_seconds": 300,
            }
        ]
        result = strip_admin_fields_from_incidents(events)
        assert len(result) == 1
        assert "error_message" not in result[0]
        assert "duration_seconds" not in result[0]
        assert result[0]["service_id"] == "openai"
        assert result[0]["new_status"] == "down"  # normalized
