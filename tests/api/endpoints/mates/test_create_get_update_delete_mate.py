import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.mates.mates_get_one import Mate, mates_get_one_output_example
from server.api.models.mates.mates_create import MatesCreateInput, MatesCreateOutput, mates_create_input_example, mates_create_output_example
from server.api.models.mates.mates_update import MatesUpdateInput, MatesUpdateOutput, mates_update_input_example, mates_update_output_example
from server.api.models.mates.mates_delete import MatesDeleteOutput, mates_delete_output_example

load_dotenv()

# test the examples from the docs
@pytest.mark.api_dependent
def test_docs_mates_create():
    try:
        validated_mate_data = MatesCreateInput(**mates_create_input_example)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesCreateInput model: {e}")

    try:
        validated_mate_data = MatesCreateOutput(**mates_create_output_example)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesCreateOutput model: {e}")


@pytest.mark.api_dependent
def test_docs_mates_get_one():
    try:
        validated_mate_data = Mate(**mates_get_one_output_example)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesGetOneOutput model: {e}")


@pytest.mark.api_dependent
def test_docs_mates_update():
    try:
        validated_mate_data = MatesUpdateInput(**mates_update_input_example)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesUpdateInput model: {e}")

    try:
        validated_mate_data = MatesUpdateOutput(**mates_update_output_example)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesUpdateOutput model: {e}")


@pytest.mark.api_dependent
def test_docs_mates_delete():
    try:
        validated_mate_data = MatesDeleteOutput(**mates_delete_output_example)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesDeleteOutput model: {e}")


# then test the actual API endpoints
@pytest.mark.api_dependent
def test_create_get_update_delete_mate():
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {"Authorization": f"Bearer {api_token}"}
    base_url = f"http://0.0.0.0:8000/v1/{team_slug}/mates"

    # TODO also update doc testing and check if all API endpoints have the full documentation correctly included

    # TODO add more testing scenarios, also test for error responses correctly triggered

    # TODO measure how long processing of responses takes

    # TODO add testing of examples also for other api endpoints

    # Prepare mate creation data
    mate_data = {
        "name": "Test Mate",
        "username": "test_mate",
        "description": "Test mate description",
        "profile_picture_url": f"/v1/{team_slug}/uploads/burton_03ba7afff9.jpeg",
        "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
        "default_skills": [1],
        "default_llm_endpoint": f"/skills/chatgpt/ask",
        "default_llm_model": "gpt-4o-mini"
    }

    # Validate input data
    try:
        validated_mate_data = MatesCreateInput(**mate_data)
    except ValidationError as e:
        pytest.fail(f"Input data does not match the MatesCreateInput model: {e}")

    # Create a mate
    create_response = requests.post(
        base_url,
        headers=headers,
        json=validated_mate_data.model_dump()
    )
    assert create_response.status_code == 201, f"Failed to create mate: {create_response.status_code}\nResponse content: {create_response.text}"

    # Validate the response
    try:
        created_mate = MatesCreateOutput.model_validate(create_response.json())
        assert created_mate.username == mate_data["username"], f"Created mate name does not match. Expected '{mate_data['username']}', got '{created_mate.username}'"
    except ValidationError as e:
        pytest.fail(f"Created mate does not match the MatesCreateOutput model: {e}\nResponse content: {create_response.text}")

    # Get and verify the created mate
    get_response = requests.get(
        f"{base_url}/{created_mate.username}",
        headers=headers
    )
    assert get_response.status_code == 200, f"Failed to get created mate from {base_url}/{created_mate.username}: {get_response.status_code}\nResponse content: {get_response.text}"
    try:
        mate = Mate.model_validate(get_response.json())
        assert mate.username == mate_data["username"], f"Created mate name does not match. Expected '{mate_data['username']}', got '{mate.username}'"
    except ValidationError as e:
        pytest.fail(f"Created mate does not match the Mate model: {e}\nResponse content: {get_response.text}")

    # Update the mate
    updated_mate_data = {
        "name": "Updated Test Mate"
    }
    update_response = requests.patch(
        f"{base_url}/{created_mate.username}",
        headers=headers,
        json=updated_mate_data
    )
    assert update_response.status_code == 200, f"Failed to update mate: {update_response.status_code}\nResponse content: {update_response.text}"
    updated_mate = update_response.json()
    try:
        updated_response = MatesUpdateOutput.model_validate(updated_mate)
        assert updated_response.updated_fields["name"] == updated_mate_data["name"], f"Mate name was not updated, got response: '{updated_response}'"
    except ValidationError as e:
        pytest.fail(f"Updated mate does not match the Mate model: {e}\nResponse content: {update_response.text}")

    # Delete the mate
    delete_response = requests.delete(
        f"{base_url}/{created_mate.username}",
        headers=headers
    )
    assert delete_response.status_code == 200, f"Failed to delete mate: {delete_response.status_code}\nResponse content: {delete_response.text}"
    deleted_mate = delete_response.json()
    try:
        deleted_mate = MatesDeleteOutput.model_validate(deleted_mate)
        assert deleted_mate.deleted_user == created_mate.username, f"Deleted mate username does not match. Expected '{created_mate.username}', got '{deleted_mate.deleted_user}'"
    except ValidationError as e:
        pytest.fail(f"Deleted mate does not match the MatesDeleteOutput model: {e}\nResponse content: {delete_response.text}")

    # Verify the mate is deleted
    get_response = requests.get(
        f"{base_url}/{created_mate.username}",
        headers=headers
    )
    assert get_response.status_code == 404, f"Mate was not deleted: {get_response.status_code}\nResponse content: {get_response.text}"
