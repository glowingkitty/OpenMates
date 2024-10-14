import pytest
import requests
import os
from dotenv import load_dotenv
from server.api.models.apps.business.skills_business_plan_application import business_plan_application_input_example
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
def test_business_plan_application():
    input_file_path = "tests/paid/api/endpoints/apps/business/hidden/test_business_plan_application_input.json"

    if os.path.exists(input_file_path):
        with open(input_file_path, "r") as input_file:
            input_data = json.load(input_file)
    else:
        input_data = business_plan_application_input_example

    response = requests.post(
        f"{BASE_URL}/v1/{TEAM_SLUG}/apps/business/plan_application",
        headers=HEADERS,
        json=input_data
    )

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()
    recipient_data = json_response.get("recipient")
    assert recipient_data, "No recipient found in the response"

    # Save the response as a markdown file
    output_folder = "tests/paid/api/endpoints/apps/business/hidden"
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    output_file = os.path.join(output_folder, "test_business_plan_application_output.md")

    def write_markdown(file, data, level=1):
        if isinstance(data, dict):
            for key, value in data.items():
                file.write(f"{'#' * level} {key.capitalize()}\n\n")
                write_markdown(file, value, level + 1)
        elif isinstance(data, list):
            for item in data:
                write_markdown(file, item, level)
        else:
            file.write(f"{data}\n\n")

    with open(output_file, "w") as md_file:
        md_file.write("# Business Plan Application Output\n\n")
        write_markdown(md_file, json_response)

    print(f"Created markdown file saved '{output_file}'")
