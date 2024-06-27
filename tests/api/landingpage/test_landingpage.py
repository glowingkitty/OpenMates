import pytest
import requests


@pytest.mark.api_dependent
def test_read_root():
    response = requests.get("http://localhost:8000/")

    # Check if the status code is 200
    assert response.status_code == 200

    # Check if the content type is HTML
    assert "text/html" in response.headers["content-type"]

    # Check if the response content contains 'OpenMates API'
    assert "Welcome to OpenMates" in response.text
