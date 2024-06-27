import pytest
import requests


def test_uploads():
    url = "http://0.0.0.0:8000/v1/glowingkitties/uploads/burton_03ba7afff9.jpeg"
    response = requests.get(url)
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('image/jpeg')