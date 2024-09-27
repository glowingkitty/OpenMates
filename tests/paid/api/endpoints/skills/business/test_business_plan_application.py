import pytest
import requests
import os
from dotenv import load_dotenv
from server.api.models.skills.business.skills_business_plan_application import business_plan_application_input_example
import json

# Load environment variables from .env file
load_dotenv()

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.mark.api_dependent
def test_business_plan_application():
    input_file_path = "tests/paid/api/endpoints/skills/business/hidden/test_business_plan_application_input.json"

    if os.path.exists(input_file_path):
        with open(input_file_path, "r") as input_file:
            input_data = json.load(input_file)
    else:
        input_data = business_plan_application_input_example

    response = requests.post(
        f"{BASE_URL}/v1/{TEAM_SLUG}/skills/business/plan_application",
        headers=HEADERS,
        json=input_data
    )

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()
    recipient_data = json_response.get("recipient")
    assert recipient_data, "No recipient found in the response"

    # Save the JSON response as a file
    # make sure the folder exists
    if not os.path.exists("tests/paid/api/endpoints/skills/business/hidden"):
        os.makedirs("tests/paid/api/endpoints/skills/business/hidden")
    with open("tests/paid/api/endpoints/skills/business/hidden/test_business_plan_application_output.json", "w") as json_file:
        json.dump(json_response, json_file, indent=4)

    print(f"Created JSON saved 'tests/paid/api/endpoints/skills/business/hidden/test_business_plan_application_output.json'")
