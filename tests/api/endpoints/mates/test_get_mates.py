import pytest
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_get_mates():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    assert api_token, "TEST_API_TOKEN not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    response = requests.get("http://0.0.0.0:8000/v1/glowingkitties/mates", headers=headers)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()
    assert "data" in json_response, f"'data' field not found in response: {json_response}"
    assert "meta" in json_response, f"'meta' field not found in response: {json_response}"

    # Check data structure
    assert isinstance(json_response["data"], list), f"Expected 'data' to be a list, got: {type(json_response['data'])}"
    for mate in json_response["data"]:
        expected_mate_fields = ["id", "name", "username", "description", "profile_picture_url"]
        for field in expected_mate_fields:
            assert field in mate, f"Field '{field}' not found in mate data: {mate}"

        assert isinstance(mate["id"], int), f"Expected 'id' to be an integer, got: {type(mate['id'])}"
        assert isinstance(mate["name"], str), f"Expected 'name' to be a string, got: {type(mate['name'])}"
        assert isinstance(mate["username"], str), f"Expected 'username' to be a string, got: {type(mate['username'])}"
        assert isinstance(mate["description"], str), f"Expected 'description' to be a string, got: {type(mate['description'])}"
        assert isinstance(mate["profile_picture_url"], str), f"Expected 'profile_picture_url' to be a string, got: {type(mate['profile_picture_url'])}"

        # Check profile_picture_url format
        assert mate["profile_picture_url"].startswith("/v1/"), f"profile_picture_url should start with '/v1/': {mate['profile_picture_url']}"
        assert "uploads/" in mate["profile_picture_url"], f"profile_picture_url should include 'uploads/': {mate['profile_picture_url']}"

    # Check meta structure
    assert "pagination" in json_response["meta"], f"'pagination' field not found in meta: {json_response['meta']}"
    pagination = json_response["meta"]["pagination"]
    expected_pagination_fields = ["page", "pageSize", "pageCount", "total"]
    for field in expected_pagination_fields:
        assert field in pagination, f"Field '{field}' not found in pagination: {pagination}"

    assert isinstance(pagination["page"], int), f"Expected 'page' to be an integer, got: {type(pagination['page'])}"
    assert isinstance(pagination["pageSize"], int), f"Expected 'pageSize' to be an integer, got: {type(pagination['pageSize'])}"
    assert isinstance(pagination["pageCount"], int), f"Expected 'pageCount' to be an integer, got: {type(pagination['pageCount'])}"
    assert isinstance(pagination["total"], int), f"Expected 'total' to be an integer, got: {type(pagination['total'])}"