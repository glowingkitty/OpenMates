import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.teams.teams_get_one import Team

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_get_team():
    # Get the API token and team slug from environment variables
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    response = requests.get(f"http://0.0.0.0:8000/v1/{team_slug}", headers=headers)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()

    try:
        # Validate the response against the Team model
        team = Team.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the Team model: {e}")

    # Additional assertions to check the content of the response
    assert team.slug == team_slug, f"Returned team slug {team.slug} does not match the requested slug {team_slug}"
    assert isinstance(team.mates, list), "Mates should be a list"
    assert isinstance(team.settings, dict), "Settings should be a dictionary"
    assert isinstance(team.invoices, list), "Invoices should be a list"
    assert isinstance(team.forbidden_skills, list), "Forbidden skills should be a list"
    assert isinstance(team.balance, float), "Balance should be a float"
    assert isinstance(team.users_allowed_to_use_team_balance, list), "Users allowed to use team balance should be a list"
    assert isinstance(team.user_count, int), "User count should be an integer"
    assert isinstance(team.admin_count, int), "Admin count should be an integer"
