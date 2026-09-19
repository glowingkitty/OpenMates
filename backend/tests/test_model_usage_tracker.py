# contract-test-file: infrastructure

from backend.apps.ai.processing.model_usage_tracker import ModelUsageTracker


def test_model_usage_tracker_preserves_cross_provider_buckets_and_success_identity() -> None:
    tracker = ModelUsageTracker()
    tracker.record_reported_usage(
        model_id="google/gemini-primary",
        input_tokens=100,
        output_tokens=10,
        user_input_tokens=30,
        system_prompt_tokens=70,
    )
    tracker.mark_successful_model("google/gemini-primary")
    tracker.record_reported_usage(
        model_id="anthropic/claude-fallback",
        input_tokens=50,
        output_tokens=5,
        user_input_tokens=15,
        system_prompt_tokens=35,
    )
    tracker.mark_successful_model("anthropic/claude-fallback")

    assert tracker.sentinel(tool_inference_iterations=1) == {
        "__cumulative_llm_usage__": True,
        "total_input_tokens": 150,
        "total_output_tokens": 15,
        "tool_inference_iterations": 1,
        "successful_model_id": "anthropic/claude-fallback",
        "usage_by_model": [
            {
                "model_id": "google/gemini-primary",
                "input_tokens": 100,
                "output_tokens": 10,
                "user_input_tokens": 30,
                "system_prompt_tokens": 70,
            },
            {
                "model_id": "anthropic/claude-fallback",
                "input_tokens": 50,
                "output_tokens": 5,
                "user_input_tokens": 15,
                "system_prompt_tokens": 35,
            },
        ],
    }


def test_model_usage_tracker_keeps_reported_failed_attempt_usage_without_marking_success() -> None:
    tracker = ModelUsageTracker()
    tracker.record_reported_usage(
        model_id="google/gemini-primary",
        input_tokens=20,
        output_tokens=0,
    )
    tracker.record_reported_usage(
        model_id="anthropic/claude-fallback",
        input_tokens=30,
        output_tokens=4,
    )
    tracker.mark_successful_model("anthropic/claude-fallback")

    sentinel = tracker.sentinel(tool_inference_iterations=0)

    assert sentinel["successful_model_id"] == "anthropic/claude-fallback"
    assert sentinel["total_input_tokens"] == 50
    assert [bucket["model_id"] for bucket in sentinel["usage_by_model"]] == [
        "google/gemini-primary",
        "anthropic/claude-fallback",
    ]
