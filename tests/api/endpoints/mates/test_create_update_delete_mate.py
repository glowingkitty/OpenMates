import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.mates.mates_get_one import Mate

load_dotenv()

@pytest.mark.api_dependent
def test_create_get_update_delete_mate():
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {"Authorization": f"Bearer {api_token}"}
    base_url = f"http://0.0.0.0:8000/v1/{team_slug}/mates"

    # Create a mate
    create_response = requests.post(
        base_url,
        headers=headers,
        json={
            "name": "Test Mate",
            "username": "test_mate",
            "description": "Test mate description",
            "profile_picture_url": f"/v1/{team_slug}/uploads/burton_03ba7afff9.jpeg",
            "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
            "default_skills": [1]
        }
    )
    assert create_response.status_code == 201, f"Failed to create mate: {create_response.status_code}\nResponse content: {create_response.text}"
    created_mate = create_response.json()

    # Get and verify the created mate
    get_response = requests.get(
        f"{base_url}/{created_mate['id']}",
        headers=headers
    )
    assert get_response.status_code == 200, f"Failed to get created mate: {get_response.status_code}\nResponse content: {get_response.text}"
    try:
        mate = Mate.model_validate(get_response.json())
        assert mate.name == "test_mate", f"Created mate name does not match. Expected 'test_mate', got '{mate.name}'"
    except ValidationError as e:
        pytest.fail(f"Created mate does not match the Mate model: {e}\nResponse content: {get_response.text}")

    # Update the mate
    update_response = requests.put(
        f"{base_url}/{created_mate['id']}",
        headers=headers,
        json={
            "name": "Updated Test Mate"
        }
    )
    assert update_response.status_code == 200, f"Failed to update mate: {update_response.status_code}\nResponse content: {update_response.text}"
    updated_mate = update_response.json()
    try:
        mate = Mate.model_validate(updated_mate)
        assert mate.name == "updated_test_mate", f"Mate name was not updated. Expected 'updated_test_mate', got '{mate.name}'"
    except ValidationError as e:
        pytest.fail(f"Updated mate does not match the Mate model: {e}\nResponse content: {update_response.text}")

    # Delete the mate
    delete_response = requests.delete(
        f"{base_url}/{created_mate['id']}",
        headers=headers
    )
    assert delete_response.status_code == 204, f"Failed to delete mate: {delete_response.status_code}\nResponse content: {delete_response.text}"

    # Verify the mate is deleted
    get_response = requests.get(
        f"{base_url}/{created_mate['id']}",
        headers=headers
    )
    assert get_response.status_code == 404, f"Mate was not deleted: {get_response.status_code}\nResponse content: {get_response.text}"
