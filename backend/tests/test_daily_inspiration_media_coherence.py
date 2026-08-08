# backend/tests/test_daily_inspiration_media_coherence.py
#
# Regression tests for Daily Inspiration text/media coherence.
# The public banner renders model-written copy next to media metadata, so the
# backend must reject records where those two artifacts describe different
# subjects before they enter the pool or public defaults.
#
# Run: python -m pytest backend/tests/test_daily_inspiration_media_coherence.py -v

from backend.apps.ai.daily_inspiration.media_coherence import is_inspiration_media_coherent


def test_rejects_international_space_station_copy_with_paris_video() -> None:
    assert is_inspiration_media_coherent(
        {
            "content_type": "video",
            "youtube_id": "DOH-HNotTaE",
            "phrase": (
                "The International Space Station orbits Earth every 90 minutes. "
                "How do astronauts live and work in microgravity?"
            ),
            "title": "Life in Space Station",
            "assistant_response": "Astronauts adapt to weightlessness and orbital science routines.",
            "category": "science",
            "video_title": "Paris Explained - YouTube",
            "video_channel_name": "Manuel Bravo",
        }
    ) is False


def test_accepts_matching_paris_architecture_copy_and_video() -> None:
    assert is_inspiration_media_coherent(
        {
            "content_type": "video",
            "youtube_id": "DOH-HNotTaE",
            "phrase": "Paris streets hide centuries of design. How did the city become this walkable?",
            "title": "Paris Architecture Explained",
            "assistant_response": "Paris combines boulevards, monuments, and dense neighborhoods into a distinct urban form.",
            "category": "history",
            "video_title": "Paris Explained - YouTube",
            "video_channel_name": "Manuel Bravo",
        }
    ) is True
