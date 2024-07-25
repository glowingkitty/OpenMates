import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.chatgpt.skills_chatgpt_ask import ChatGPTAskOutput

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_chatgpt_ask():
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
        "ai_model": "gpt-4o",
        "temperature": 0.5
    }

    response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/chatgpt/ask", headers=headers, json=data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        result = ChatGPTAskOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ChatGPTAskOutput model: {e}")

    assert result.response, "No response received from ChatGPT"
    assert "Paris" in result.response, "Expected 'Paris' to be in the response"


# TODO: add check for if user has setup their own token, or else has enough money in account