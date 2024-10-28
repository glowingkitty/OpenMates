import json
import pytest
import requests
import os
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join('server', '.env'))

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

# TODO add test for cancel task (and start it again)

@pytest.mark.api_dependent
def test_maps_search_places():
    data = {
        "query": "restaurant in Berlin"
    }

    response = requests.post(
        f"{BASE_URL}/v1/{TEAM_SLUG}/apps/maps/search_places",
        headers=HEADERS,
        data=data
    )

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"