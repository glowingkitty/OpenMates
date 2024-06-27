import pytest
import requests

@pytest.fixture(scope="session", autouse=True)
def check_api_server():
    response = requests.get("http://0.0.0.0:8000")
    if response.status_code != 200:
        pytest.fail("API server is not online")

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "api_dependent: mark test as dependent on API"
    )