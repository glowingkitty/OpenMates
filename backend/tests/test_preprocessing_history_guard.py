"""
Regression tests for preprocessing message-history guards.

Interactive question answers are user messages with hidden protocol JSON. The
preprocessing provider must never receive a history whose final role is an
assistant/system message, because providers like Mistral reject that shape.
"""

from backend.apps.ai.utils.preprocessing_history import normalize_preprocessing_message_history


def test_preprocessing_history_preserves_interactive_response_as_last_user() -> None:
    history = [
        {"role": "assistant", "content": "```interactive_question\n{}\n```", "created_at": 100},
        {
            "role": "user",
            "content": "Option 1\n\n```interactive_response\n{\"id\":\"q1\"}\n```",
            "created_at": 101,
        },
    ]

    normalized = normalize_preprocessing_message_history(history)

    assert normalized[-1]["role"] == "user"
    assert "interactive_response" in normalized[-1]["content"]


def test_preprocessing_history_drops_trailing_standardized_error() -> None:
    history = [
        {"role": "user", "content": "Question", "created_at": 100},
        {
            "role": "assistant",
            "content": "The AI service encountered an error while processing your request. Please try again in a moment.",
            "created_at": 101,
        },
    ]

    normalized = normalize_preprocessing_message_history(history)

    assert normalized[-1]["role"] == "user"
    assert len(normalized) == 1
