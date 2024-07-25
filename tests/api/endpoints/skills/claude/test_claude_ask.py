import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.claude.skills_claude_ask import ClaudeAskOutput

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_claude_ask():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    data = {
        "message": "What is the capital of France?",
        "system_prompt": "You only respond with the city name.",
        "ai_model": "claude-3-haiku",
        "temperature": 0.5
    }

    response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/claude/ask", headers=headers, json=data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        result = ClaudeAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeAskOutput model: {e}")

    assert result.response, "No response received from Claude"
    assert "Paris" in result.response, "Expected 'Paris' to be in the response"

# TODO: add test for all ai_models
# TODO: add check for if user has setup their own token, or else has enough money in account