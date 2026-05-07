# backend/tests/test_daily_inspiration_video_processor.py
#
# Regression tests for Daily Inspiration video candidate filtering.
# These tests keep YouTube audience metadata handling deterministic without
# calling external APIs.
# The production pipeline enriches candidates first, then rejects unsuitable
# audience flags before ranking or LLM selection.

from backend.apps.ai.daily_inspiration.video_processor import _filter_made_for_kids


def test_filter_made_for_kids_rejects_youtube_flagged_video() -> None:
    candidates = [
        {
            "youtube_id": "kid123",
            "title": "Colorful Chemistry Lesson",
            "made_for_kids": True,
        },
        {
            "youtube_id": "adult123",
            "title": "General Chemistry Explainer",
            "made_for_kids": False,
        },
        {
            "youtube_id": "unknown123",
            "title": "Brave-only Candidate",
        },
    ]

    filtered = _filter_made_for_kids(candidates, "test_task", "chemistry basics")

    assert [candidate["youtube_id"] for candidate in filtered] == [
        "adult123",
        "unknown123",
    ]
