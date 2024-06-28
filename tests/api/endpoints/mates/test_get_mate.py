import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.mates.mates_get_one import Mate

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_get_mate():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    response = requests.get(f"http://0.0.0.0:8000/v1/{team_slug}/mates/burton", headers=headers)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        mate = Mate.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the Mate model: {e}")