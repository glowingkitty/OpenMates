import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.claude.skills_claude_ask import ClaudeAskOutput

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

def make_request(message, system_prompt, ai_model, stream=False):
    data = {
        "message": message,
        "system_prompt": system_prompt,
        "ai_model": ai_model,
        "temperature": 0.5,
        "stream": stream
    }
    return requests.post(f"{BASE_URL}/v1/{TEAM_SLUG}/skills/claude/ask", headers=HEADERS, json=data, stream=stream)

@pytest.mark.api_dependent
def test_claude_ask_non_streaming(claude_model):
    response = make_request("What is the capital of France?", "You only respond with the city name.", claude_model)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.response, "No response received from Claude"
    assert "Paris" in result.response, "Expected 'Paris' to be in the response"

@pytest.mark.api_dependent
def test_claude_ask_streaming(claude_model):
    response = make_request("Count from 1 to 5.", "You are a helpful assistant.", claude_model, stream=True)

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

# TODO: add check for if user has setup their own token, or else has enough money in account