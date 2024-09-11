import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.ai.skills_ai_ask import (
    AiAskInput,
    AiAskOutput,
    AiAskOutputStream,
    ai_ask_input_example,
    ai_ask_input_example_2,
    ai_ask_input_example_3,
    ai_ask_input_example_4,
    ai_ask_output_example,
    ai_ask_output_example_2,
    ai_ask_output_example_3,
    ai_ask_output_example_4,
)
import base64
import json

# Load environment variables from .env file
load_dotenv()

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

@pytest.fixture(params=[
    {"name": "claude", "model": "claude-3-haiku"},
    {"name": "claude", "model": "claude-3.5-sonnet"},
    {"name": "chatgpt", "model": "gpt-4o-mini"},
    {"name": "chatgpt", "model": "gpt-4o"}
])
def ai_provider(request):
    return request.param

def make_request(**kwargs):
    return requests.post(f"{BASE_URL}/v1/{TEAM_SLUG}/skills/ai/ask", headers=HEADERS, json=kwargs)


@pytest.mark.api_dependent
def test_ai_ask_examples_validity():
    input_examples = [
        ai_ask_input_example,
        ai_ask_input_example_2,
        ai_ask_input_example_3,
        ai_ask_input_example_4
    ]

    output_examples = [
        ai_ask_output_example,
        ai_ask_output_example_2,
        ai_ask_output_example_3,
        ai_ask_output_example_4
    ]

    for example in input_examples:
        try:
            AiAskInput.model_validate(example)
        except ValidationError as e:
            print(f"Example that failed validation: {example}")
            pytest.fail(f"Example is not valid: {e}")

    for example in output_examples:
        try:
            AiAskOutput.model_validate(example)
        except ValidationError as e:
            print(f"Example that failed validation: {example}")
            pytest.fail(f"Example is not valid: {e}")


@pytest.mark.api_dependent
def test_ai_ask(ai_provider):
    input_data = ai_ask_input_example.copy()
    input_data["provider"] = ai_provider
    response = make_request(**input_data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = AiAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AiAskOutput model: {e}")

    assert result.content, "No response received from AI"
    assert any("Berlin" in item.get("text", "") for item in result.content if item.get("type", "") == "text"), "Expected 'Berlin' to be in the response"


@pytest.mark.api_dependent
def test_ai_ask_with_message_history(ai_provider):
    message_history = [
        {"role": "user", "content": "What's the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
        {"role": "user", "content": "And Germany?"}
    ]
    response = make_request(message_history=message_history, provider=ai_provider)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = AiAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AiAskOutput model: {e}")

    assert result.content, "No response received from AI"
    assert any("Berlin" in item.get("text", "") for item in result.content if item.get("type", "") == "text"), "Expected 'Berlin' to be in the response"


@pytest.mark.api_dependent
@pytest.mark.skipif(not os.path.exists("tests/api/endpoints/skills/ai/test_ai_ask_example_image.jpg"), reason="Test image not found")
def test_ai_ask_with_image(ai_provider):
    image_path = "tests/api/endpoints/skills/ai/test_ai_ask_example_image.jpg"
    with open(image_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode('utf-8')

    message_history = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": "What's in this image?"
                }
            ]
        }
    ]

    response = make_request(message_history=message_history, provider=ai_provider)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = AiAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AiAskOutput model: {e}")

    assert result.content, "No response received from AI"
    assert any(word in item.get("text", "").lower() for item in result.content if item.get("type", "") == "text" for word in ["boat", "ship"]), "Expected 'boat' or 'ship' to be mentioned in the response"


@pytest.mark.api_dependent
def test_ai_ask_with_tool_use(ai_provider):
    tools = [
        {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"]
                    }
                },
                "required": ["location"]
            }
        }
    ]

    response = make_request(
        message="What's the weather like in San Francisco in celcius?",
        system="You are a helpful assistant. Use the provided tools when necessary.",
        provider=ai_provider,
        tools=tools
    )

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = AiAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AiAskOutput model: {e}")

    assert result.content, "No response received from AI"

    tool_use_items = [item for item in result.content if item["type"] == "tool_use"]
    assert tool_use_items, "Expected at least one tool_use in the response"

    tool_use = tool_use_items[0]["tool_use"]
    assert tool_use["name"] == "get_current_weather", "Expected the get_current_weather tool to be used"
    assert "San Francisco" in tool_use["input"]["location"], "Expected San Francisco to be in the location"


@pytest.mark.api_dependent
def test_ai_ask_with_tool_result(ai_provider):
    # Simulate getting the stock price
    stock_price = 150.25  # This would normally come from calling the actual function

    # Define the tools
    tools = [
        {
            "name": "get_stock_price",
            "description": "Get the current stock price for a given ticker symbol.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "The stock ticker symbol, e.g. AAPL for Apple Inc."
                    }
                },
                "required": ["ticker"]
            }
        }
    ]

    # Create a message history with the tool result
    message_history = [
        {"role": "user", "content": "What's the current stock price of Apple?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_01VvRuf8tfQY2oWJ9GwohaE4", "name": "get_stock_price", "input": {"ticker": "AAPL"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01VvRuf8tfQY2oWJ9GwohaE4", "content": str(stock_price)}]}
    ]

    # Make a new request with the tool result
    input_data = {
        "system": "You are a helpful assistant. Keep your answers short.",
        "message_history": message_history,
        "provider": ai_provider,
        "temperature": 0.5,
        "max_tokens": 150,
        "tools": tools
    }

    response = make_request(**input_data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = AiAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AiAskOutput model: {e}")

    assert result.content, "No response received from AI"
    assert any(item["type"] == "text" for item in result.content), "Expected a text response"

    text_response = next(item["text"] for item in result.content if item["type"] == "text")
    assert "150.25" in text_response, "Expected the stock price to be mentioned in the response"
    assert "Apple" in text_response, "Expected 'Apple' to be mentioned in the response"


@pytest.mark.api_dependent
@pytest.mark.parametrize("use_tools", [False, True])
def test_ai_ask_streaming(ai_provider, use_tools):
    tools = [
        {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"]
                    }
                },
                "required": ["location"]
            }
        }
    ] if use_tools else None

    message = "What's the weather like in San Francisco in celsius?" if use_tools else "Tell me about the history of San Francisco."
    system = "You are a helpful assistant. Use the provided tools when necessary." if use_tools else "You are a helpful assistant. Provide concise information."

    request_data = {
        "message": message,
        "system": system,
        "provider": ai_provider,
        "stream": True,
        "tools": tools
    }

    response = make_request(**request_data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"
    assert response.headers.get('content-type').startswith('text/event-stream'), "Expected content-type to start with text/event-stream"

    full_response = ""
    tool_use_detected = False
    content_chunks = []
    tool_use_events = []

    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                stream_event = AiAskOutputStream.model_validate_json(decoded_line)
                print(f"Received event: {stream_event.model_dump_json()}")

                if stream_event.content:
                    if isinstance(stream_event.content, dict):
                        if stream_event.content.get("type") == "text":
                            content_chunks.append(stream_event.content.get("text", ""))
                            full_response += stream_event.content.get("text", "")
                        elif stream_event.content.get("type") == "tool_use":
                            tool_use_detected = True
                            tool_use_events.append(stream_event.content.get("tool_use", {}))
                            print(f"Tool use detected: {json.dumps(stream_event.content.get('tool_use', {}))}")
                elif stream_event.stream_end:
                    break

    # Add assertions
    assert full_response or tool_use_detected, "Expected a non-empty response or tool use to be detected"

    if use_tools:
        assert tool_use_detected, "Expected tool use to be detected when tools are provided"
        assert len(tool_use_events) > 0, "Expected at least one tool use event when tools are provided"
        assert tool_use_events[0].get("name", "") == "get_current_weather", "Expected the get_current_weather tool to be used"
        assert "San Francisco" in tool_use_events[0].get("input", {}).get("location", ""), "Expected San Francisco to be in the location for tool use"

        if content_chunks:
            assert "weather" in full_response.lower(), "Expected 'weather' to be mentioned in the response when using tools"
            assert "San Francisco" in full_response, "Expected 'San Francisco' to be mentioned in the response when using tools"
    else:
        assert not tool_use_detected, "Did not expect tool use to be detected when tools are not provided"
        assert "San Francisco" in full_response, "Expected 'San Francisco' to be mentioned in the response"
        assert any(word in full_response.lower() for word in ["history", "founded", "city"]), "Expected some historical information about San Francisco in the response"

    # Verify that the last event was a stream_end event
    assert stream_event.stream_end, "Expected the last event to be a stream_end event"