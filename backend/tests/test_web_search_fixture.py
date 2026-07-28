# backend/tests/test_web_search_fixture.py
#
# Deterministic coverage for the web/search E2E fixture hook.
# The hook is intentionally limited to non-production environments and an
# explicit query token so provider-backed E2E rendering can avoid Brave quota
# without affecting normal web searches.

from backend.apps.web.skills.search_fixture import (
    E2E_WEB_FIXTURE_QUERY_TOKEN,
    build_e2e_web_fixture_results,
    is_e2e_web_fixture_query,
)


def test_e2e_web_fixture_query_is_dev_only(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert is_e2e_web_fixture_query(E2E_WEB_FIXTURE_QUERY_TOKEN) is True

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert is_e2e_web_fixture_query(E2E_WEB_FIXTURE_QUERY_TOKEN) is False


def test_e2e_web_fixture_results_match_web_preview_shape() -> None:
    results = build_e2e_web_fixture_results(1)

    assert len(results) == 1
    assert results[0]["type"] == "search_result"
    assert results[0]["title"]
    assert results[0]["url"].startswith("https://app.dev.openmates.org/")
    assert results[0]["description"]
