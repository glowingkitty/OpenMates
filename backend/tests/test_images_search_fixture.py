# backend/tests/test_images_search_fixture.py
#
# Deterministic coverage for the images/search E2E fixture hook.
# The hook is intentionally limited to non-production environments and an
# explicit query token so provider-backed E2E rendering can avoid Brave quota
# without affecting normal image searches.

from backend.apps.images.skills.search_skill import (
    E2E_IMAGE_FIXTURE_QUERY_TOKEN,
    _build_e2e_image_fixture_results,
    _is_e2e_image_fixture_query,
)


def test_e2e_image_fixture_query_is_dev_only(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert _is_e2e_image_fixture_query(E2E_IMAGE_FIXTURE_QUERY_TOKEN) is True

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert _is_e2e_image_fixture_query(E2E_IMAGE_FIXTURE_QUERY_TOKEN) is False


def test_e2e_image_fixture_results_match_image_preview_shape() -> None:
    results = _build_e2e_image_fixture_results(1)

    assert len(results) == 1
    assert results[0]["type"] == "image_result"
    assert results[0]["image_url"].startswith("https://app.dev.openmates.org/")
    assert results[0]["thumbnail_url"].startswith("https://app.dev.openmates.org/")
