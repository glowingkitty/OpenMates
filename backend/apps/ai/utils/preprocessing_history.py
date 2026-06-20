"""
backend/apps/ai/utils/preprocessing_history.py

Lightweight preprocessing history helpers shared by LLM utility code and tests.
Kept provider-free so deploy gates can validate history normalization without
importing optional provider SDKs such as tiktoken.
"""

from typing import Any, Dict, List


STANDARDIZED_USER_ERROR_MESSAGE = (
    "The AI service encountered an error while processing your request. "
    "Please try again in a moment."
)


def normalize_preprocessing_message_history(message_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove trailing standardized-error assistant turns before preprocessing calls."""
    normalized = list(message_history)
    while normalized:
        last_message = normalized[-1]
        last_role = last_message.get("role") or ("user" if last_message.get("sender_name") == "user" else "assistant")
        if last_role == "user":
            break
        if str(last_message.get("content") or "").strip() == STANDARDIZED_USER_ERROR_MESSAGE:
            normalized.pop()
            continue
        break
    return normalized
