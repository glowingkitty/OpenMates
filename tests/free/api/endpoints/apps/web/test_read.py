import pytest
import requests
import os
import time
import json
from dotenv import load_dotenv
from pydantic import ValidationError
from server.api.models.apps.web.skills_web_read import WebReadOutput, web_read_input_examples
from concurrent.futures import ThreadPoolExecutor, as_completed

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

    # urls = web_read_input_examples
    urls = ["https://nlnet.nl/propose/"]
    request_times = []  # List to store request times

    # Create 'hidden' directory if it doesn't exist
    hidden_dir = "tests/free/api/endpoints/apps/web/hidden"
    os.makedirs(hidden_dir, exist_ok=True)

    def make_request(url, include_images):
        params = {
            "url": url,
            "include_images": include_images
        }
        start_time = time.time()  # Start timing
        response = requests.post(f"http://0.0.0.0:8000/v1/{team_slug}/apps/web/read", headers=headers, json=params)
        end_time = time.time()  # End timing

        request_time_ms = (end_time - start_time) * 1000  # Calculate time in ms
        result = {
            "url": url,
            "include_images": include_images,
            "time_ms": request_time_ms,
            "response": response
        }
        return result

    with ThreadPoolExecutor() as executor:
        futures = []
        for url in urls:
            for include_images in [True, False]:
                futures.append(executor.submit(make_request, url, include_images))

        for future in as_completed(futures):
            result = future.result()
            url = result["url"]
            include_images = result["include_images"]
            response = result["response"]
            request_times.append({
                "url": url,
                "include_images": include_images,
                "time_ms": result["time_ms"]
            })

            assert response.status_code == 200, f"Unexpected status code: {response.status_code} for URL: {url}, include_images: {include_images}"

            json_response = response.json()

            try:
                # Validate the response against the WebReadOutput model
                web_read_output = WebReadOutput(**json_response)

                # Shorten the URL for filenames
                shortened_url = url[:20]  # Adjust the number of characters as needed

                # Save markdown to file
                markdown_filename = f"{hidden_dir}/test_read_output_{shortened_url.replace('/', '_')}_{include_images}.md"
                with open(markdown_filename, "w") as f:
                    f.write(web_read_output.content)

                # Save HTML to file
                html_filename = f"{hidden_dir}/test_read_output_{shortened_url.replace('/', '_')}_{include_images}.html"
                with open(html_filename, "w") as f:
                    f.write(web_read_output.html)

                # Save author if available
                if hasattr(web_read_output, 'authors'):
                    request_times[-1]['authors'] = web_read_output.authors

            except ValidationError as e:
                pytest.fail(f"Response does not match the WebReadOutput model: {e}, with response: {json_response}")

    # Save request times to a JSON file
    with open(f"{hidden_dir}/request_times.json", "w") as f:
        json.dump(request_times, f, indent=4)