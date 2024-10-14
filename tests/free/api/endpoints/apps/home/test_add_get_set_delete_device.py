import pytest
import requests
import os
from dotenv import load_dotenv
from server.api.models.apps.home.skills_home_add_device import home_add_device_input_example
# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join('server', '.env'))

@pytest.mark.api_dependent
def test_add_get_set_delete_device():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    # Add a device
    add_device_response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/apps/home/add_device", headers=headers, json=home_add_device_input_example)
    assert add_device_response.status_code == 200, f"Unexpected status code: {add_device_response.status_code} for API endpoint 'http://0.0.0.0:8000/v1/{team_slug}/apps/home/add_device'"

    # Get the device
    get_device_response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/apps/home/get_device", headers=headers, json={
        "id": home_add_device_input_example["id"]
    })
    assert get_device_response.status_code == 200, f"Unexpected status code: {get_device_response.status_code} for API endpoint 'http://0.0.0.0:8000/v1/{team_slug}/apps/home/get_device'"

    # Set the device
    set_device_response = requests.put(f"http://0.0.0.0:8000/v1/{team_slug}/apps/home/set_device", headers=headers, json={
        "id": home_add_device_input_example["id"],
        "command": {
            "state": "power",
            "value": "on"
        }
    })
    assert set_device_response.status_code == 200, f"Unexpected status code: {set_device_response.status_code} for API endpoint 'http://0.0.0.0:8000/v1/{team_slug}/apps/home/set_device'"

    # Delete the device
    delete_device_response = requests.delete(f"http://0.0.0.0:8000/v1/{team_slug}/apps/home/delete_device", headers=headers, json={
        "id": home_add_device_input_example["id"]
    })
    assert delete_device_response.status_code == 200, f"Unexpected status code: {delete_device_response.status_code} for API endpoint 'http://0.0.0.0:8000/v1/{team_slug}/apps/home/delete_device'"