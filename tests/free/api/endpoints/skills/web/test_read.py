import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
import markdown
from urllib.parse import quote
from server.api.models.skills.web.skills_web_read import WebReadOutput, web_read_input_examples


# Load environment variables from .env file
load_dotenv()

@pytest.mark.api_dependent
def test_read():
    # Get the API token from environment variable
    api_token = os.getenv('TEST_API_TOKEN')
    team_slug = os.getenv('TEST_TEAM_SLUG')
    assert api_token, "TEST_API_TOKEN not found in .env file"
    assert team_slug, "TEST_TEAM_SLUG not found in .env file"

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    urls = web_read_input_examples

    for url in urls:
        response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/web/read", headers=headers, json={"url": url})

        assert response.status_code == 200, f"Unexpected status code: {response.status_code} for URL: {url}"

        json_response = response.json()

        try:
            # Validate the response against the WebReadOutput model
            web_read_output = WebReadOutput(**json_response)

            # Check if the content is valid markdown
            assert markdown.markdown(web_read_output.content), f"Invalid markdown content for URL: {url}"

            # Create a URL-safe filename from the title
            safe_filename = quote(web_read_output.title, safe='') + '.md'

            # Save the markdown content to a file
            with open(safe_filename, 'w', encoding='utf-8') as f:
                f.write(web_read_output.content)

            print(f"Saved markdown file: {safe_filename}")

        except ValidationError as e:
            pytest.fail(f"Response does not match the WebReadOutput model: {e}, with response: {json_response}")