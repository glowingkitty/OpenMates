import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.claude.skills_claude_ask import ClaudeAskOutput
import base64
from server.api.models.skills.claude.skills_claude_ask import claude_ask_input_example_2, claude_ask_input_example_3

# Load environment variables from .env file
load_dotenv()

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

@pytest.fixture(params=["claude-3-haiku", "claude-3.5-sonnet"])
def claude_model(request):
    return request.param

def make_request(**kwargs):
    return requests.post(f"{BASE_URL}/v1/{TEAM_SLUG}/skills/claude/ask", headers=HEADERS, json=kwargs)

@pytest.mark.api_dependent
def test_claude_ask_non_streaming(claude_model):
    response = make_request(message="What is the capital of France?", ai_model=claude_model)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.content, "No response received from Claude"
    assert "Paris" in result.content[0].text, "Expected 'Paris' to be in the response"

@pytest.mark.api_dependent
def test_claude_ask_with_message_history(claude_model):
    message_history = [
        {"role": "user", "content": "What's the capital of France"},
        {"role": "assistant", "content": "The capital city of France is Paris."},
        {"role": "user", "content": "And Germany?"}
    ]
    response = make_request(message_history=message_history, ai_model=claude_model)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.content, "No response received from Claude"
    assert "Berlin" in result.content[0].text, "Expected 'Berlin' to be in the response"

@pytest.mark.api_dependent
def test_claude_ask_streaming(claude_model):
    response = make_request(message="Count from 1 to 5.", system="You are a helpful assistant.", ai_model=claude_model, stream=True)

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

    assert full_response, f"No response received from {claude_model}"
    assert "1" in full_response and "5" in full_response, f"Expected numbers from 1 to 5 in the response from {claude_model}"

@pytest.mark.api_dependent
def test_claude_ask_with_image(claude_model):
    # Load the image file
    image_path = os.path.join(os.path.dirname(__file__), "test_claude_ask_example_image.jpg")
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

    response = make_request(message_history=message_history, ai_model=claude_model)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.content, "No response received from Claude"
    assert any(word in result.content[0].text.lower() for word in ["boat", "ship"]), "Expected 'boat' or 'ship' to be mentioned in the response"

@pytest.mark.api_dependent
def test_claude_ask_with_tool_use(claude_model):
    # Use claude_ask_input_example_2 from skills_claude_ask.py
    input_data = claude_ask_input_example_2.copy()
    input_data["ai_model"] = claude_model  # Update the model to use the pytest fixture

    response = make_request(**input_data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.content, "No response received from Claude"
    assert any(item.type == "tool_use" for item in result.content), "Expected a tool_use in the response"
    tool_use = next(item for item in result.content if item.type == "tool_use")
    assert tool_use.tool_use["name"] == "get_stock_price", "Expected the get_stock_price tool to be used"
    assert tool_use.tool_use["input"]["ticker"] == "AAPL", "Expected the ticker to be AAPL"

@pytest.mark.api_dependent
def test_claude_ask_with_tool_interpretation(claude_model):
    # Use claude_ask_input_example_3 from skills_claude_ask.py
    input_data = claude_ask_input_example_3.copy()
    input_data["ai_model"] = claude_model  # Update the model to use the pytest fixture

    response = make_request(**input_data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.content, "No response received from Claude"
    assert result.content[0].type == "text", "Expected a text response"
    assert "$150.25" in result.content[0].text, "Expected the stock price to be mentioned in the response"
    assert "Apple" in result.content[0].text, "Expected 'Apple' to be mentioned in the response"

# TODO: add check for if user has setup their own token, or else has enough money in account