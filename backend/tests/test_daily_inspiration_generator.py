# backend/tests/test_daily_inspiration_generator.py
#
# Regression tests for the Daily Inspiration generation orchestrator.
# These tests focus on post-LLM assembly behavior, where mismatches between
# generated text and selected media can be introduced if metadata policies
# mutate the video after the LLM has already written the phrase.
#
# Run: python -m pytest backend/tests/test_daily_inspiration_generator.py -v

from types import SimpleNamespace
import asyncio
import sys
import types
import importlib

fake_llm_utils = types.ModuleType("backend.apps.ai.utils.llm_utils")


class FakeLLMPreprocessingCallResult(SimpleNamespace):
    def __init__(self, error_message=None, arguments=None, **kwargs):
        super().__init__(error_message=error_message, arguments=arguments or {}, **kwargs)


fake_llm_utils.LLMPreprocessingCallResult = FakeLLMPreprocessingCallResult
fake_llm_utils.call_preprocessing_llm = None
fake_llm_utils.truncate_message_history_to_token_budget = lambda message_history, **_kwargs: message_history
sys.modules["backend.apps.ai.utils.llm_utils"] = fake_llm_utils


def test_age_policy_drops_slot_instead_of_swapping_unrelated_video(monkeypatch):
    """Do not keep neutron-star text if the selected video gets age-rejected."""
    generator = importlib.import_module("backend.apps.ai.daily_inspiration.generator")

    async def fake_find_video_candidates(*_args, **_kwargs):
        return [
            {
                "youtube_id": "neutron1234",
                "title": "Why Neutron Stars Are So Dense",
                "thumbnail_url": "https://img.youtube.com/vi/neutron1234/hqdefault.jpg",
                "channel_name": "Independent Science",
                "view_count": 1000,
                "duration_seconds": 600,
                "published_at": "2019-01-01T00:00:00Z",
            },
            {
                "youtube_id": "hiking12345",
                "title": "Hiking the Malerweg I Adventure Trail",
                "thumbnail_url": "https://img.youtube.com/vi/hiking12345/hqdefault.jpg",
                "channel_name": "Trail Stories",
                "view_count": 2000,
                "duration_seconds": 700,
                "published_at": "2025-01-01T00:00:00Z",
            },
        ]

    async def fake_call_preprocessing_llm(*_args, **_kwargs):
        return SimpleNamespace(
            error_message=None,
            arguments={
                "inspirations": [
                    {
                        "phrase": "Neutron stars are among the densest objects. What makes them fascinating?",
                        "title": "Neutron Star Density",
                        "assistant_response": "Neutron stars compress enormous mass into a tiny sphere.",
                        "category": "science",
                        "selected_video_youtube_id": "neutron1234",
                        "follow_up_suggestions": [
                            "How dense are neutron stars?",
                            "What creates neutron stars?",
                            "Could we visit one?",
                        ],
                    }
                ]
            },
        )

    async def fake_validate_inspiration(*_args, **_kwargs):
        return True

    monkeypatch.setattr(generator, "find_video_candidates", fake_find_video_candidates)
    monkeypatch.setattr(generator, "call_preprocessing_llm", fake_call_preprocessing_llm)
    monkeypatch.setattr(generator, "validate_inspiration", fake_validate_inspiration)

    inspirations = asyncio.run(
        generator.generate_inspirations(
            user_id="user-123",
            count=1,
            topic_suggestions=["neutron stars"],
            secrets_manager=SimpleNamespace(),
            task_id="test_age_policy_mismatch",
            language="en",
        )
    )

    assert inspirations == []
