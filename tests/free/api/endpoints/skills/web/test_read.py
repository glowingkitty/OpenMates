import pytest
import requests
import os
import time
import json
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

    # urls = ["https://www.digitalwaffle.co/job/product-designer-51"]
    urls = web_read_input_examples
    request_times = []  # List to store request times

    # Create 'hidden' directory if it doesn't exist
    hidden_dir = "tests/free/api/endpoints/skills/web/hidden"
    os.makedirs(hidden_dir, exist_ok=True)

    for url in urls:
        for include_images in [True, False]:
            params = {
                "url": url,
                "include_images": include_images
            }
            start_time = time.time()  # Start timing
            response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/skills/web/read", headers=headers, json=params)
            end_time = time.time()  # End timing

            request_time_ms = (end_time - start_time) * 1000  # Calculate time in ms
            request_times.append({
                "url": url,
                "include_images": include_images,
                "time_ms": request_time_ms
            })

            assert response.status_code == 200, f"Unexpected status code: {response.status_code} for URL: {url}, include_images: {include_images}"

            json_response = response.json()

            try:
                # Validate the response against the WebReadOutput model
                web_read_output = WebReadOutput(**json_response)

                # Check if the content is valid markdown
                # assert markdown.markdown(web_read_output.content), f"Invalid markdown content for URL: {url}, include_images: {include_images}"

                # Check for image tags in the content
                # image_tags = re.findall(r'!\[.*?\]\(.*?\)', web_read_output.content)
                # if include_images:
                #     assert image_tags, f"No image tags found in content when include_images=True for URL: {url}"
                # else:
                #     assert not image_tags, f"Image tags found in content when include_images=False for URL: {url}"

                # save markdown to file
                markdown_filename = f"{hidden_dir}/test_read_output_{url.replace('/', '_')}_{include_images}.md"
                with open(markdown_filename, "w") as f:
                    f.write(web_read_output.content)

                # Save author if available
                if hasattr(web_read_output, 'authors'):
                    request_times[-1]['authors'] = web_read_output.authors

            except ValidationError as e:
                pytest.fail(f"Response does not match the WebReadOutput model: {e}, with response: {json_response}")

    # Save request times to a JSON file
    with open(f"{hidden_dir}/request_times.json", "w") as f:
        json.dump(request_times, f, indent=4)