# TODOimport pytest
import os
import base64
from fastapi.testclient import TestClient
from server.api.endpoints.skills.files.upload import upload
from server.api.endpoints.skills.files.download import download
from server.api.endpoints.skills.files.delete import delete
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from server.api.models.skills.files.skills_files_delete import FilesDeleteOutput
from fastapi.responses import StreamingResponse
import pytest
import requests
from datetime import datetime, timedelta
# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"

HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

@pytest.fixture
def test_file_path():
    return "tests/api/endpoints/skills/files/test_file.docx"

@pytest.fixture
def test_file_data(test_file_path):
    with open(test_file_path, "rb") as file:
        return file.read()

@pytest.mark.api_dependent
def test_upload_download_delete_file(test_file_data, test_file_path):
    expiration_datetime = datetime.now() + timedelta(days=1)

    # upload file
    response = requests.post(
        f"{BASE_URL}/v1/{TEAM_SLUG}/skills/files/upload",
        headers=HEADERS,
        files={"file": ("test_file.docx", test_file_data)},
        data={
            "provider": "openmates",
            "file_name": "test_file.docx",
            "folder_path": "docs", # turns into file_path 'docs/{file_id}/test_file.docx' if provider openmates
            "expiration_datetime": expiration_datetime.isoformat(),
            "access_public": False
        }
    )
    assert response.status_code == 200, "Upload failed"
    upload_file = response.json()
    print(upload_file)
    assert upload_file["name"] == "test_file.docx", "File name does not match"

    # download file
    response = requests.get(
        f"{BASE_URL}{upload_file['url']}",
        headers=HEADERS
    )
    assert response.status_code == 200, "Download failed"
    downloaded_data = response.content
    assert downloaded_data == test_file_data, "Downloaded file data does not match uploaded data"

    # delete file
    response = requests.delete(
        f"{BASE_URL}{upload_file['url']}",
        headers=HEADERS
    )
    assert response.status_code == 200, "Delete failed"
    delete_response = response.json()
    assert delete_response["success"] == True, "File was not successfully deleted"