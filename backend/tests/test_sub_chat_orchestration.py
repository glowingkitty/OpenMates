# backend/tests/test_sub_chat_orchestration.py
#
# Unit coverage for sub-chat fan-out limits.
# These tests validate the backend-owned guardrails without invoking real LLM,
# Directus, or Celery execution. The frontend E2E spec covers the inline
# confirmation UI that is shown for large approved batches.

from backend.apps.ai.sub_chat_orchestration import (
    MAX_DIRECT_SUB_CHATS_PER_PARENT,
    MAX_TEMPLATE_EXPANSION_ITEMS,
    expand_sub_chat_requests,
    validate_sub_chat_capacity,
)


def test_template_expansion_is_capped() -> None:
    expanded = expand_sub_chat_requests([
        {
            "prompt_template": "Research {x}",
            "list": [str(index) for index in range(MAX_TEMPLATE_EXPANSION_ITEMS + 5)],
        }
    ])

    assert len(expanded) == MAX_TEMPLATE_EXPANSION_ITEMS
    assert expanded[0]["prompt"] == "Research 0"
    assert expanded[-1]["prompt"] == f"Research {MAX_TEMPLATE_EXPANSION_ITEMS - 1}"


def test_capacity_allows_requests_within_direct_sub_chat_limit() -> None:
    result = validate_sub_chat_capacity(existing_count=17, requested_count=3)

    assert result["allowed"] is True
    assert result["remaining"] == 3


def test_capacity_rejects_requests_above_direct_sub_chat_limit() -> None:
    result = validate_sub_chat_capacity(existing_count=19, requested_count=2)

    assert result["allowed"] is False
    assert result["remaining"] == 1
    assert str(MAX_DIRECT_SUB_CHATS_PER_PARENT) in result["message"]
