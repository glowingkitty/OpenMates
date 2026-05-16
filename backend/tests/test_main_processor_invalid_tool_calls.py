# backend/tests/test_main_processor_invalid_tool_calls.py
# Regression tests for invalid AI tool-call handling in main processing.
# Invalid LLM-emitted tools must not execute or surface as embeds, but their
# streamed tool_use blocks still need matched tool_result entries for provider
# protocol integrity across Gemini, Bedrock, OpenAI, Anthropic, and Mistral.

import json
from types import SimpleNamespace

from backend.apps.ai.processing.main_processor import (
    INVALID_TOOL_FALLBACK_MESSAGE,
    INVALID_TOOL_RESULT_REASON,
    _append_tool_call_turn_to_history,
)


def test_invalid_tool_calls_are_hidden_protocol_bookkeeping() -> None:
    history = []
    valid_tool = SimpleNamespace(
        tool_call_id="valid-call",
        function_name="web-search",
        function_arguments_raw='{"query":"gamescom dates"}',
        thought_signature="valid-signature",
    )
    invalid_tool = SimpleNamespace(
        tool_call_id="invalid-call",
        function_name="travel-search_flights",
        function_arguments_raw='{"from":"BER"}',
        thought_signature="invalid-signature",
    )
    rejection_message = {
        "tool_call_id": invalid_tool.tool_call_id,
        "role": "tool",
        "name": invalid_tool.function_name,
        "content": json.dumps({"status": "rejected", "reason": INVALID_TOOL_RESULT_REASON}),
    }

    _append_tool_call_turn_to_history(
        history,
        tool_calls=[valid_tool],
        rejected_tool_calls=[(invalid_tool, rejection_message)],
        assistant_content="",
    )

    assert len(history) == 2
    assistant_message = history[0]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"] is None
    assert [call["id"] for call in assistant_message["tool_calls"]] == ["valid-call", "invalid-call"]
    assert assistant_message["tool_calls"][0]["thought_signature"] == "valid-signature"
    assert assistant_message["tool_calls"][1]["thought_signature"] == "invalid-signature"

    tool_result = history[1]
    result_payload = json.loads(tool_result["content"])
    assert tool_result["tool_call_id"] == "invalid-call"
    assert result_payload["status"] == "rejected"
    assert "travel-search_flights" not in result_payload["reason"]
    assert "unavailable internal tools" in result_payload["reason"]


def test_invalid_tool_fallback_message_does_not_name_internal_tools() -> None:
    assert "travel-search_flights" not in INVALID_TOOL_FALLBACK_MESSAGE
    assert "tool" not in INVALID_TOOL_FALLBACK_MESSAGE.lower()
