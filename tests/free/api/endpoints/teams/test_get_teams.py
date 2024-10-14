import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.teams.teams_get_all import TeamsGetAllOutput

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join('server', '.env'))

@pytest.mark.api_dependent
def test_get_teams():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    assert api_token, "TEST_API_TOKEN not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    response = requests.get("http://0.0.0.0:8000/v1/teams", headers=headers)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        teams = TeamsGetAllOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the TeamsGetAllOutput model: {e}")

    # Additional assertions
    assert len(teams.teams) > 0, "No teams returned"
    for team in teams.teams:
        assert team.id > 0, "Team ID should be positive"
        assert len(team.name) > 0, "Team name should not be empty"
        assert len(team.slug) > 0, "Team slug should not be empty"
