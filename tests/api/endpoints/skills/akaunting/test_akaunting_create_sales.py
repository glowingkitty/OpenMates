import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.akaunting.skills_akaunting_create_income import AkauntingCreateIncomeOutput

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_create_income():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    data = {
        "customer": {
            "name": "John Doe",
            "address": "123 Main St, Anytown, AN 12345",
            "country": "United States"
        },
        "invoice": {
            "items": [
                {
                    "name": "Product A",
                    "price": 100.00,
                    "vat": 20.00,
                    "total": 120.00,
                    "quantity": 1
                }
            ],
            "date": "2023-06-01"
        },
        "bank_transaction": {
            "value": 120.00,
            "date": "2023-06-01"
        }
    }

    response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/akaunting/create_income", headers=headers, json=data)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        result = AkauntingCreateIncomeOutput.model_validate(json_response)
    except ValidationError as e:
        pytest.fail(f"Response does not match the AkauntingCreateIncomeOutput model: {e}")

    assert result.success, f"Failed to create sales: {result.message}"
