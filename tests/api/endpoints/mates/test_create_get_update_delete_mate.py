import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.mates.mates_get_one import Mate
from server.api.models.mates.mates_create import MatesCreateInput, MatesCreateOutput
from server.api.models.mates.mates_update import MatesUpdateInput, MatesUpdateOutput
from server.api.models.mates.mates_delete import MatesDeleteOutput

load_dotenv()

@pytest.fixture(scope="module")
def api_config():
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {"Authorization": f"Bearer {api_token}"}
    base_url = f"http://0.0.0.0:8000/v1/{team_slug}/mates"

    return {"headers": headers, "base_url": base_url, "team_slug": team_slug}

def create_mate(config, mate_data):
    create_response = requests.post(
        config["base_url"],
        headers=config["headers"],
        json=mate_data
    )
    assert create_response.status_code == 201, f"Failed to create mate: {create_response.status_code}\nResponse content: {create_response.text}"
    return MatesCreateOutput.model_validate(create_response.json())

def update_mate(config, username, update_data):
    update_response = requests.patch(
        f"{config['base_url']}/{username}",
        headers=config["headers"],
        json=update_data
    )
    assert update_response.status_code == 200, f"Failed to update mate: {update_response.status_code}\nResponse content: {update_response.text}"
    return MatesUpdateOutput.model_validate(update_response.json())

def delete_mate(config, username):
    delete_response = requests.delete(
        f"{config['base_url']}/{username}",
        headers=config["headers"]
    )
    assert delete_response.status_code == 200, f"Failed to delete mate: {delete_response.status_code}\nResponse content: {delete_response.text}"
    return MatesDeleteOutput.model_validate(delete_response.json())

def verify_mate_deleted(config, username):
    get_response = requests.get(
        f"{config['base_url']}/{username}",
        headers=config["headers"]
    )
    assert get_response.status_code == 404, f"Mate was not deleted: {get_response.status_code}\nResponse content: {get_response.text}"

@pytest.mark.api_dependent
def test_create_update_delete_mate_basic(api_config):
    mate_data = {
        "name": "Test Mate",
        "username": "test_mate_basic",
        "description": "Test mate description",
        "profile_picture_url": f"/v1/{api_config['team_slug']}/uploads/burton_03ba7afff9.jpeg",
        "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
        "default_skills": [1],
        "default_llm_endpoint": f"/v1/{api_config['team_slug']}/skills/chatgpt/ask",
        "default_llm_model": "gpt-4o-mini"
    }

    created_mate = create_mate(api_config, mate_data)
    assert created_mate.username == mate_data["username"]

    update_data = {"name": "Updated Test Mate"}
    updated_mate = update_mate(api_config, created_mate.username, update_data)
    assert updated_mate.updated_fields["name"] == update_data["name"]

    deleted_mate = delete_mate(api_config, created_mate.username)
    assert deleted_mate.deleted_user == created_mate.username

    verify_mate_deleted(api_config, created_mate.username)

@pytest.mark.api_dependent
def test_create_update_delete_mate_with_youtube_skill(api_config):
    mate_data = {
        "name": "YouTube Skill Mate",
        "username": "youtube_skill_mate",
        "description": "Mate with YouTube skill",
        "profile_picture_url": f"/v1/{api_config['team_slug']}/uploads/burton_03ba7afff9.jpeg",
        "default_systemprompt": "You are a YouTube content expert.",
        "default_skills": [f'/v1/{api_config["team_slug"]}/skills/youtube/transcript'],
        "default_llm_endpoint": f"/v1/{api_config['team_slug']}/skills/chatgpt/ask",
        "default_llm_model": "gpt-4o-mini"
    }

    created_mate = create_mate(api_config, mate_data)
    assert created_mate.username == mate_data["username"]

    update_data = {"default_skills": [1, 2]}
    updated_mate = update_mate(api_config, created_mate.username, update_data)
    assert "default_skills" in updated_mate.updated_fields

    deleted_mate = delete_mate(api_config, created_mate.username)
    assert deleted_mate.deleted_user == created_mate.username

@pytest.mark.api_dependent
def test_create_update_delete_mate_multiple_updates(api_config):
    mate_data = {
        "name": "Multi Update Mate",
        "username": "multi_update_mate",
        "description": "Mate for testing multiple updates",
        "profile_picture_url": f"/v1/{api_config['team_slug']}/uploads/burton_03ba7afff9.jpeg",
        "default_systemprompt": "You are a versatile AI assistant.",
        "default_skills": [1],
        "default_llm_endpoint": f"/v1/{api_config['team_slug']}/skills/chatgpt/ask",
        "default_llm_model": "gpt-4o-mini"
    }

    created_mate = create_mate(api_config, mate_data)

    updates = [
        {"description": "Updated description"},
        {"default_systemprompt": "You are an expert in multiple domains."},
        {"default_skills": [1, 2, 3]},
        {"default_llm_endpoint": f"/v1/{api_config['team_slug']}/skills/chatgpt/ask", "default_llm_model": "gpt-4o"},
        {"allowed_to_access_user_name": True, "allowed_to_access_user_projects": True}
    ]

    for update in updates:
        updated_mate = update_mate(api_config, created_mate.username, update)
        for key, value in update.items():
            if key == "default_skills":
                # Check if the updated skills match the expected IDs
                assert [skill['id'] for skill in updated_mate.updated_fields[key]] == value
            else:
                if key in updated_mate.updated_fields:
                    assert updated_mate.updated_fields[key] == value
                else:
                    raise KeyError(f"Key '{key}' not found in updated_mate.updated_fields. Full updated_mate content: '{updated_mate}' for update: '{update}'")

    deleted_mate = delete_mate(api_config, created_mate.username)
    assert deleted_mate.deleted_user == created_mate.username

@pytest.mark.api_dependent
def test_create_mate_validation_error(api_config):
    invalid_mate_data = {
        "name": "Invalid Mate",
        "username": "INVALID_USERNAME",
        "description": "This mate should fail validation",
        "profile_picture_url": "invalid_url",
        "default_systemprompt": "",
        "default_skills": ["invalid_skill"],
        "default_llm_endpoint": "invalid_endpoint",
        "default_llm_model": "invalid_model"
    }

    with pytest.raises(ValidationError):
        MatesCreateInput(**invalid_mate_data)

@pytest.mark.api_dependent
def test_update_mate_validation_error(api_config):
    mate_data = {
        "name": "Valid Mate",
        "username": "valid_mate",
        "description": "This mate is valid",
        "profile_picture_url": f"/v1/{api_config['team_slug']}/uploads/burton_03ba7afff9.jpeg",
        "default_systemprompt": "You are a test mate.",
        "default_skills": [1],
        "default_llm_endpoint": f"/v1/{api_config['team_slug']}/skills/chatgpt/ask",
        "default_llm_model": "gpt-4o"
    }

    created_mate = create_mate(api_config, mate_data)

    invalid_update_data = {
        "username": "INVALID_USERNAME",
        "profile_picture_url": "invalid_url",
        "default_llm_endpoint": "invalid_endpoint",
        "default_llm_model": "invalid_model"
    }

    with pytest.raises(ValidationError):
        MatesUpdateInput(**invalid_update_data)

    delete_mate(api_config, created_mate.username)

# Add more test scenarios as needed