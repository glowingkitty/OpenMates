import pytest
import requests
import os
from dotenv import load_dotenv
from server.api.models.apps.business.skills_business_create_pitch import business_create_pitch_input_example
import json

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join('server', '.env'))

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.mark.api_dependent
def test_business_create_pitch():
    input_file_path = "tests/paid/api/endpoints/apps/business/hidden/test_business_create_pitch_input.json"

    if os.path.exists(input_file_path):
        with open(input_file_path, "r") as input_file:
            input_data = json.load(input_file)
    else:
        input_data = business_create_pitch_input_example

    response = requests.post(
        f"{BASE_URL}/v1/{TEAM_SLUG}/apps/business/create_pitch",
        headers=HEADERS,
        json=input_data
    )

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()
    pitch_data = json_response.get("pitch")
    assert pitch_data, "No pitch found in the response"

    # Save the "pitch" field as a markdown file
    # make sure the folder exists
    if not os.path.exists("tests/paid/api/endpoints/apps/business/hidden"):
        os.makedirs("tests/paid/api/endpoints/apps/business/hidden")
    with open("tests/paid/api/endpoints/apps/business/hidden/test_business_create_pitch_output.md", "w") as md_file:
        md_file.write(pitch_data)

    print(f"Created pitch saved 'tests/paid/api/endpoints/apps/business/hidden/test_business_create_pitch_output.md'")
