import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.claude.skills_claude_estimate_cost import ClaudeEstimateCostOutput

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_estimate_cost():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    payload = {
        "system": "You are a helpful assistant.",
        "message": "What is the capital of France?",
        "message_history": [
            {"role": "human", "content": "Hello, Claude!"},
            {"role": "assistant", "content": "Hello! How can I assist you today?"}
        ],
        "tools": []
    }

    response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/claude/estimate_cost", headers=headers, json=payload)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        estimate_cost_output = ClaudeEstimateCostOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the ClaudeEstimateCostOutput model: {e}")

    # Additional assertions
    assert estimate_cost_output.usage.input_tokens > 0, "Input tokens should be greater than 0"
    assert estimate_cost_output.estimated_cost.input > 0, "Input cost should be greater than 0"
    assert estimate_cost_output.estimated_cost.output_100tokens > 0, "Output cost for 100 tokens should be greater than 0"
    assert estimate_cost_output.estimated_cost.output_500tokens > 0, "Output cost for 500 tokens should be greater than 0"
    assert estimate_cost_output.estimated_cost.output_2000tokens > 0, "Output cost for 2000 tokens should be greater than 0"
