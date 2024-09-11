import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from server.api.models.skills.docs.skills_docs_create import docs_create_input_example
from io import BytesIO
from docx import Document

# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_create_doc():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/docs/create", headers=headers, json=docs_create_input_example)

    assert response.status_code == 200, f"Unexpected status code: {response.status_code} for API endpoint 'http://0.0.0.0:8000/v1/{team_slug}/skills/docs/create'"

    json_response = response.json()

    try:
        # Validate the response against your Pydantic model
        file_info = FilesUploadOutput.model_validate(json_response)

        # Then download the file, and check if the content is ok
        downloaded_file_response = requests.get(f"http://0.0.0.0:8000/{file_info.url}", headers=headers)
        assert downloaded_file_response.status_code == 200, f"Unexpected status code: {downloaded_file_response.status_code} for API endpoint 'http://0.0.0.0:8000/{file_info.url}'"

        # Read the .docx file content
        doc = Document(BytesIO(downloaded_file_response.content))
        doc_text = "\n".join([paragraph.text for paragraph in doc.paragraphs])

        # check that the ['title'] field in the response is the same as the input
        assert docs_create_input_example['title'] in doc_text, f"Didn't find the title ('{docs_create_input_example['title']}') in the downloaded file content: {doc_text} for API endpoint 'http://0.0.0.0:8000/{file_info.url}'"

        # If all good, then delete the file based on the url in the response
        requests.delete(f"http://0.0.0.0:8000/{file_info.url}", headers=headers)
    except ValidationError as e:
        pytest.fail(f"Response does not match the Skill model: {e}, with response: {json_response}")