import pytest
import requests
import os


@pytest.mark.api_dependent
def test_uploads():
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"
    url = f"http://0.0.0.0:8000/v1/{team_slug}/uploads/burton_03ba7afff9.jpeg"
    response = requests.get(url)
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('image/jpeg')