import json
import pytest
import requests
import os
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

API_TOKEN = os.getenv('TEST_API_TOKEN')
TEAM_SLUG = os.getenv('TEST_TEAM_SLUG')
BASE_URL = "http://0.0.0.0:8000"

assert API_TOKEN, "TEST_API_TOKEN not found in .env file"
assert TEAM_SLUG, "TEST_TEAM_SLUG not found in .env file"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

ebook_path = "tests/paid/api/endpoints/skills/books/test_ebook.epub"

# TODO add test for cancel task (and start it again)

@pytest.mark.api_dependent
@pytest.mark.skipif(not os.path.exists(ebook_path), reason="Test ebook not found")
def test_books_translate():
    with open(ebook_path, "rb") as ebook_file:
        files = {"file": (ebook_path.split("/")[-1], ebook_file, "application/epub+zip")}
        data = {"output_language": "german", "output_format": "pdf"}

        response = requests.post(
            f"{BASE_URL}/v1/{TEAM_SLUG}/skills/books/translate",
            headers=HEADERS,
            files=files,
            data=data
        )

    assert response.status_code == 200, f"Unexpected status code: {response.status_code}: {response.text}"

    json_response = response.json()
    task_url = json_response.get("url")
    assert task_url, "No task_url found in the response"

    # Poll the task status
    polling_interval = 2  # Time between polling attempts in seconds

    while True:
        task_response = requests.get(f"{BASE_URL}{task_url}", headers=HEADERS)
        assert task_response.status_code == 200, f"Unexpected status code: {task_response.status_code}: {task_response.text}"

        task_json = task_response.json()
        status = task_json.get("status")
        error = task_json.get("error")

        if status == "completed" or error is not None:
            break

        time.sleep(polling_interval)

    assert status == "completed", f"Task did not complete successfully: {task_json}"
    assert "output" in task_json, "No output found in the task response"
    assert "url" in task_json["output"], "No url found in the task output"

    # Save task output details as JSON
    with open("tests/paid/api/endpoints/skills/books/task_output.json", "w") as json_file:
        json.dump(task_json, json_file, indent=2)

    # Get the translated ebook
    translated_ebook_url = task_json["output"]["url"]
    translated_ebook_response = requests.get(f"{BASE_URL}{translated_ebook_url}", headers=HEADERS)

    assert translated_ebook_response.status_code == 200, f"Unexpected status code: {translated_ebook_response.status_code}: {translated_ebook_response.text}"
    assert translated_ebook_response.content, "No content received from the translated ebook URL"

    # Optionally, save the translated ebook to a file for further inspection
    with open(f"tests/paid/api/endpoints/skills/books/{ebook_path.split('/')[-1].split('.')[0]}_{data['output_language']}.{data['output_format']}", "wb") as translated_file:
        translated_file.write(translated_ebook_response.content)

    print(f"Translated ebook saved as '{ebook_path.split('/')[-1].split('.')[0]}_{data['output_language']}.{data['output_format']}'")
