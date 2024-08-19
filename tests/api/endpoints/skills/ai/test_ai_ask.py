import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.ai.skills_ai_ask import (
    AiAskInput,
    AiAskOutput,
    ai_ask_input_example,
    ai_ask_input_example_2,
    ai_ask_input_example_3,
    ai_ask_input_example_4,
    ai_ask_output_example,
    ai_ask_output_example_2,
    ai_ask_output_example_3,
    ai_ask_output_example_4
)
import base64

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
    assert any("Berlin" in item.text for item in result.content if item.type == "text"), "Expected 'Berlin' to be in the response"

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
    assert any("Berlin" in item.text for item in result.content if item.type == "text"), "Expected 'Berlin' to be in the response"

@pytest.mark.api_dependent
@pytest.mark.skipif(not os.path.exists("tests/api/endpoints/skills/claude/test_claude_ask_example_image.jpg"), reason="Test image not found")
def test_ai_ask_with_image(ai_provider):
    if ai_provider["name"] != "claude":
        pytest.skip("Image analysis is only supported for Claude")

    image_path = "tests/api/endpoints/skills/claude/test_claude_ask_example_image.jpg"
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
    assert any(word in item.text.lower() for item in result.content if item.type == "text" for word in ["boat", "ship"]), "Expected 'boat' or 'ship' to be mentioned in the response"

@pytest.mark.api_dependent
def test_ai_ask_with_tool_use(ai_provider):
    if ai_provider["name"] != "claude":
        pytest.skip("Tool use is only supported for Claude")

    input_data = ai_ask_input_example_2.copy()
    input_data["provider"] = ai_provider

    response = make_request(**input_data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = AiAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AiAskOutput model: {e}")

    assert result.content, "No response received from AI"
    assert any(item.type == "tool_use" for item in result.content), "Expected a tool_use in the response"
    tool_use = next(item for item in result.content if item.type == "tool_use")
    assert tool_use.tool_use["name"] == "get_stock_price", "Expected the get_stock_price tool to be used"
    assert tool_use.tool_use["input"]["ticker"] == "AAPL", "Expected the ticker to be AAPL"

@pytest.mark.api_dependent
def test_ai_ask_streaming(ai_provider):
    if ai_provider["name"] == "chatgpt":
        pytest.skip("Streaming is not supported for ChatGPT")

    response = make_request(message="Count from 1 to 5.", system="You are a helpful assistant.", provider=ai_provider, stream=True)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"
    assert response.headers.get('content-type').startswith('text/event-stream'), "Expected content-type to start with text/event-stream"

    full_response = ""
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data: "):
                chunk = decoded_line[6:]
                full_response += chunk
                print(chunk, end='', flush=True)
            elif decoded_line == "event: stream_end":
                break

    assert full_response, f"No response received from {ai_provider['name']}"
    assert "1" in full_response and "5" in full_response, f"Expected numbers from 1 to 5 in the response from {ai_provider['name']}"