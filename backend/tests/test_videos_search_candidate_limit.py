# backend/tests/test_videos_search_candidate_limit.py
#
# Deterministic tests for the videos/search direct execution budget.
# The live skill enriches Brave results with YouTube metadata and LLM
# sanitization before returning to CLI/API callers, so candidate fan-out must
# stay bounded to keep direct app-skill calls responsive.

from backend.apps.videos.skills.search_skill import (
    MAX_RETURNED_VIDEO_RESULTS,
    _candidate_count_for_requested_count,
)


def test_video_search_candidate_count_keeps_default_request_small() -> None:
    assert _candidate_count_for_requested_count(6) == 10


def test_video_search_candidate_count_caps_large_requests() -> None:
    assert _candidate_count_for_requested_count(50) == MAX_RETURNED_VIDEO_RESULTS


def test_video_search_candidate_count_keeps_tiny_requests_useful() -> None:
    assert _candidate_count_for_requested_count(1) == 8
