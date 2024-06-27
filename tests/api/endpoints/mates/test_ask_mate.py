import pytest
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def test_ask_mate():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    assert api_token, "TEST_API_TOKEN not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }
    payload = {
        "mate_username": "burton",
        "message": "hello world"
    }

    response = requests.post("http://0.0.0.0:8000/v1/glowingkitties/mates/ask", json=payload, headers=headers)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()
    expected_fields = ["message", "tokens_used_input", "tokens_used_output", "total_costs_eur"]
    for field in expected_fields:
        assert field in json_response, f"Field '{field}' not found in response: {json_response}"

    assert isinstance(json_response["message"], str), f"Expected 'message' to be a string, got: {type(json_response['message'])}"
    assert isinstance(json_response["tokens_used_input"], int), f"Expected 'tokens_used_input' to be an integer, got: {type(json_response['tokens_used_input'])}"
    assert isinstance(json_response["tokens_used_output"], int), f"Expected 'tokens_used_output' to be an integer, got: {type(json_response['tokens_used_output'])}"
    assert isinstance(json_response["total_costs_eur"], float), f"Expected 'total_costs_eur' to be a float, got: {type(json_response['total_costs_eur'])}"