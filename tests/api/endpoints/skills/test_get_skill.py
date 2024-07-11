import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.skills_get_one import Skill

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_get_skill():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    endpoint = "claude/ask"
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    response = requests.get(f"http://0.0.0.0:8000/v1/{team_slug}/skills/{endpoint}", headers=headers)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code} for API endpoint 'http://0.0.0.0:8000/v1/{team_slug}/skills/{endpoint}'"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        skill = Skill.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the Skill model: {e}, with response: {json_response}")