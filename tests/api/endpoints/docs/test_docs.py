import pytest
from fastapi.testclient import TestClient
from server.api.api import app

@pytest.fixture
def client():
    return TestClient(app)

def test_read_root(client):
    response = client.get("/docs")
    print(response.text)

    # Check if the status code is 200
    assert response.status_code == 200

    # Check if the content type is HTML
    assert "text/html" in response.headers["content-type"]

    # Check if the response content is the ReDoc
    assert "ReDoc requires Javascript to function." in response.text
