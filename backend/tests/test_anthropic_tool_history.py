# contract-test-file: infrastructure

import copy

import pytest

from backend.apps.ai.llm_providers.anthropic_shared import _prepare_messages_with_caching


def test_anthropic_tool_continuation_preserves_calls_and_groups_parallel_results() -> None:
    history = [
        {"role": "user", "content": "Compare Berlin and Paris weather."},
        {
            "role": "assistant",
            "content": "I will check both cities.",
            "tool_calls": [
                {
                    "id": "weather-berlin",
                    "type": "function",
                    "function": {
                        "name": "weather-forecast",
                        "arguments": '{"location":"Berlin","days":2}',
                    },
                },
                {
                    "id": "weather-paris",
                    "type": "function",
                    "function": {
                        "name": "weather-forecast",
                        "arguments": '{"location":"Paris","days":2}',
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "weather-berlin",
            "name": "weather-forecast",
            "content": '{"temperature_c":18}',
        },
        {
            "role": "tool",
            "tool_call_id": "weather-paris",
            "name": "weather-forecast",
            "content": '{"temperature_c":21}',
        },
    ]
    original_history = copy.deepcopy(history)

    converted = _prepare_messages_with_caching(history)

    assert history == original_history
    assert converted == [
        {"role": "user", "content": "Compare Berlin and Paris weather."},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will check both cities."},
                {
                    "type": "tool_use",
                    "id": "weather-berlin",
                    "name": "weather-forecast",
                    "input": {"location": "Berlin", "days": 2},
                },
                {
                    "type": "tool_use",
                    "id": "weather-paris",
                    "name": "weather-forecast",
                    "input": {"location": "Paris", "days": 2},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "weather-berlin",
                    "content": [{"type": "text", "text": '{"temperature_c":18}'}],
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "weather-paris",
                    "content": [{"type": "text", "text": '{"temperature_c":21}'}],
                },
            ],
        },
    ]


def test_anthropic_tool_result_keeps_multimodal_content_and_call_id() -> None:
    converted = _prepare_messages_with_caching([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "view-1",
                    "type": "function",
                    "function": {"name": "images-view", "arguments": '{"image_id":"one"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "view-1",
            "name": "images-view",
            "content": [
                {"type": "text", "text": "Rendered image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
            ],
        },
    ])

    assert converted[0]["content"][0] == {
        "type": "tool_use",
        "id": "view-1",
        "name": "images-view",
        "input": {"image_id": "one"},
    }
    assert converted[1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "view-1",
        "content": [
            {"type": "text", "text": "Rendered image"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "YQ==",
                },
            },
        ],
    }


def test_anthropic_tool_history_rejects_malformed_arguments_instead_of_rewriting_them() -> None:
    with pytest.raises(ValueError, match="tool-bad.*invalid JSON arguments"):
        _prepare_messages_with_caching([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tool-bad",
                        "type": "function",
                        "function": {"name": "weather-forecast", "arguments": "{not-json"},
                    }
                ],
            }
        ])
