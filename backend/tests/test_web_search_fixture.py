# backend/tests/test_web_search_fixture.py
#
# Deterministic coverage for the web/search E2E fixture hook.
# The hook is intentionally limited to non-production environments and an
# explicit query token so provider-backed E2E rendering can avoid Brave quota
# without affecting normal web searches.

import asyncio

import pytest
from unittest.mock import AsyncMock

from backend.apps.web.skills.search_fixture import (
    E2E_WEB_FIXTURE_QUERY_TOKEN,
    build_e2e_web_fixture_results,
    is_e2e_web_fixture_query,
    wait_throttled_search_provider_fixture,
)
from backend.apps.web.skills.search_skill import SearchSkill


def _skill() -> SearchSkill:
    return SearchSkill(
        app=None,
        app_id="web",
        skill_id="search",
        skill_name="Search the web",
        skill_description="Find web results.",
    )


# contract-test: infrastructure
def test_e2e_web_fixture_query_is_dev_only(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert is_e2e_web_fixture_query(E2E_WEB_FIXTURE_QUERY_TOKEN) is True

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert is_e2e_web_fixture_query(E2E_WEB_FIXTURE_QUERY_TOKEN) is False


# contract-test: infrastructure
def test_e2e_web_fixture_results_match_web_preview_shape() -> None:
    results = build_e2e_web_fixture_results(1)

    assert len(results) == 1
    assert results[0]["type"] == "search_result"
    assert results[0]["title"]
    assert results[0]["url"].startswith("https://app.dev.openmates.org/")
    assert results[0]["description"]


# contract-test: infrastructure
def test_e2e_web_fixture_accepts_llm_string_request(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    async def run_search():
        return await _skill().execute(
            requests=[E2E_WEB_FIXTURE_QUERY_TOKEN],
            secrets_manager=object(),
        )

    response = asyncio.run(run_search())
    payload = response.model_dump()

    assert payload["error"] is None
    assert payload["results"][0]["id"] == 1
    assert payload["results"][0]["results"][0]["title"] == "OpenMates E2E Web Fixture"


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.video.source-frame-provenance
@pytest.mark.parametrize("missing_guard", [None, "CI", "OPENMATES_CI_ISOLATED", "OPENMATES_CI_AI_FIXTURES", "MOCK_EXTERNAL_APIS"])
def test_camera_provider_latency_requires_exact_query_and_all_isolated_guards(monkeypatch, missing_guard):
    from backend.apps.web.skills import search_fixture
    for key, value in {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_AI_FIXTURES": "1", "MOCK_EXTERNAL_APIS": "true"}.items():
        monkeypatch.setenv(key, value)
    if missing_guard:
        monkeypatch.delenv(missing_guard)
    delay = AsyncMock()
    monkeypatch.setattr(search_fixture.asyncio, "sleep", delay)
    asyncio.run(search_fixture.wait_camera_search_provider_fixture(search_fixture.E2E_WEB_FIXTURE_QUERY_TOKEN))
    delay.assert_not_awaited()
    asyncio.run(search_fixture.wait_camera_search_provider_fixture(search_fixture.E2E_CAMERA_SEARCH_QUERY))
    if missing_guard:
        delay.assert_not_awaited()
    else:
        delay.assert_awaited_once_with(1)


# contract-test: infrastructure
@pytest.mark.parametrize("guard", ["CI", "OPENMATES_CI_ISOLATED", "OPENMATES_CI_AI_FIXTURES", "MOCK_EXTERNAL_APIS", "SERVER_ENVIRONMENT"])
def test_provider_throttle_fixture_requires_isolated_replay(monkeypatch, guard):
    from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode
    for key, value in {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_AI_FIXTURES": "1",
                       "MOCK_EXTERNAL_APIS": "true", "SERVER_ENVIRONMENT": "development"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(guard, "production" if guard == "SERVER_ENVIRONMENT" else "false")
    activate_mock_mode("mock", "mercury_auto_low")
    try:
        # Accessing this object as a cache would fail: no product cache/HTTP is reached.
        asyncio.run(wait_throttled_search_provider_fixture(
            f"{E2E_WEB_FIXTURE_QUERY_TOKEN} throttle 00000000-0000-4000-8000-000000000000 0", object(),
        ))
    finally:
        deactivate_mock_mode()
