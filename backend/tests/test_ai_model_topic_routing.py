"""Explicit model-family requests survive incomplete preprocessing output."""

# contract-test-file: infrastructure

from backend.apps.ai.processing.ai_model_topic_routing import complete_ai_model_topics


def test_explicit_multifamily_model_request_recovers_missed_families() -> None:
    request = (
        "Using the OpenMates model catalogue, name recent language models and "
        "recent image, video, and audio models with release dates."
    )
    assert complete_ai_model_topics(["llm", "audio"], request) == ["llm", "audio", "image", "video"]


def test_content_generation_does_not_load_model_catalogue() -> None:
    assert complete_ai_model_topics([], "Generate an image of a cat and a short video.") == []
    assert complete_ai_model_topics(["video"], "Create a video for me.") == ["video"]
