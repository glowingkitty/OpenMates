import pytest
import requests
import os
from dotenv import load_dotenv
from pydantic import ValidationError
import markdown
import re
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
        for include_images in [True, False]:
            params = {
                "url": url,
                "include_images": include_images
            }
            response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/web/read", headers=headers, json=params)

            assert response.status_code == 200, f"Unexpected status code: {response.status_code} for URL: {url}, include_images: {include_images}"

            json_response = response.json()

            try:
                # Validate the response against the WebReadOutput model
                web_read_output = WebReadOutput(**json_response)

                # Check if the content is valid markdown
                assert markdown.markdown(web_read_output.content), f"Invalid markdown content for URL: {url}, include_images: {include_images}"

                # Check for image tags in the content
                image_tags = re.findall(r'!\[.*?\]\(.*?\)', web_read_output.content)
                if include_images:
                    assert image_tags, f"No image tags found in content when include_images=True for URL: {url}"
                else:
                    assert not image_tags, f"Image tags found in content when include_images=False for URL: {url}"


                # # save markdown to file
                # with open(f"tests/free/api/endpoints/skills/web/test_read_output_{url.replace('/', '_')}_{include_images}.md", "w") as f:
                #     f.write(web_read_output.content)

            except ValidationError as e:
                pytest.fail(f"Response does not match the WebReadOutput model: {e}, with response: {json_response}")