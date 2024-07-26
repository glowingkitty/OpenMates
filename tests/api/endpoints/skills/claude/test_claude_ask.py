import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.claude.skills_claude_ask import ClaudeAskOutput
import base64

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

def make_request(message=None, message_history=None, system_prompt="You only respond with the city name.", ai_model="claude-3.5-sonnet", stream=False):
    data = {
        "system_prompt": system_prompt,
        "ai_model": ai_model,
        "temperature": 0.5,
        "stream": stream
    }
    if message:
        data["message"] = message
    if message_history:
        data["message_history"] = message_history
    return requests.post(f"{BASE_URL}/v1/{TEAM_SLUG}/skills/claude/ask", headers=HEADERS, json=data, stream=stream)

@pytest.mark.api_dependent
def test_claude_ask_non_streaming(claude_model):
    response = make_request(message="What is the capital of France?", ai_model=claude_model)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.response, "No response received from Claude"
    assert "Paris" in result.response, "Expected 'Paris' to be in the response"

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

    assert result.response, "No response received from Claude"
    assert "Berlin" in result.response, "Expected 'Berlin' to be in the response"

@pytest.mark.api_dependent
def test_claude_ask_streaming(claude_model):
    response = make_request(message="Count from 1 to 5.", system_prompt="You are a helpful assistant.", ai_model=claude_model, stream=True)

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

    assert result.response, "No response received from Claude"
    assert any(word in result.response.lower() for word in ["boat", "ship"]), "Expected 'boat' or 'ship' to be mentioned in the response"

# TODO: add check for if user has setup their own token, or else has enough money in account