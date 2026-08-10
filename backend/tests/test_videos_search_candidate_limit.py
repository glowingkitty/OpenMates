# backend/tests/test_videos_search_candidate_limit.py
#
# Deterministic tests for the videos/search direct execution budget.
# The live skill enriches Brave results with YouTube metadata and LLM
# sanitization before returning to CLI/API callers, so candidate fan-out must
# stay bounded to keep direct app-skill calls responsive.

from backend.apps.videos.skills.search_skill import (
    E2E_VIDEO_FIXTURE_QUERY_TOKEN,
    MAX_RETURNED_VIDEO_RESULTS,
    _build_e2e_video_fixture_results,
    _candidate_count_for_requested_count,
    _is_e2e_video_fixture_query,
    _video_candidates_for_brave_results,
)


def test_video_search_candidate_count_keeps_default_request_small() -> None:
    assert _candidate_count_for_requested_count(6) == 10


def test_video_search_candidate_count_caps_large_requests() -> None:
    assert _candidate_count_for_requested_count(50) == MAX_RETURNED_VIDEO_RESULTS


def test_video_search_candidate_count_keeps_tiny_requests_useful() -> None:
    assert _candidate_count_for_requested_count(1) == 8


def test_video_candidates_prefer_youtube_results() -> None:
    candidates, has_youtube_candidates = _video_candidates_for_brave_results(
        [
            {"url": "https://example.com/video/python"},
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        ],
        8,
    )

    assert has_youtube_candidates is True
    assert candidates == [("dQw4w9WgXcQ", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})]


def test_video_candidates_fall_back_to_bounded_brave_results_without_youtube_urls() -> None:
    brave_results = [
        {"url": "https://video.example.test/python-1"},
        {"url": "https://video.example.test/python-2"},
        {"url": "https://video.example.test/python-3"},
    ]

    candidates, has_youtube_candidates = _video_candidates_for_brave_results(brave_results, 2)

    assert has_youtube_candidates is False
    assert candidates == [("", brave_results[0]), ("", brave_results[1])]


def test_e2e_video_fixture_query_is_dev_only(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert _is_e2e_video_fixture_query(E2E_VIDEO_FIXTURE_QUERY_TOKEN) is True

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert _is_e2e_video_fixture_query(E2E_VIDEO_FIXTURE_QUERY_TOKEN) is False


def test_e2e_video_fixture_results_match_video_preview_shape() -> None:
    results = _build_e2e_video_fixture_results(1)

    assert len(results) == 1
    assert results[0]["title"]
    assert results[0]["url"].startswith("https://www.youtube.com/watch?v=")
    assert results[0]["thumbnail"]["original"]
