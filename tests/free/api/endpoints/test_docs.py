import pytest
from urllib.parse import urljoin

@pytest.mark.api_dependent
def test_read_root():
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        pytest.skip("Playwright or BeautifulSoup4 is not installed. Run 'pip install playwright bs4' and 'playwright install' to run this test.")

    base_url = "http://localhost:8000"
    docs_url = f"{base_url}/docs"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(docs_url)

        # Wait for the content to load
        page.wait_for_selector('img')

        # Get the rendered HTML
        content = page.content()

        soup = BeautifulSoup(content, 'html.parser')
        img_tags = soup.find_all('img')

        print(f"Number of img tags found: {len(img_tags)}")

        assert img_tags, "No images found in the documentation"

        missing_images = []
        for img in img_tags:
            src = img.get('src')
            if not src:
                missing_images.append(f"Image tag without src attribute: {img}")
                continue

            img_url = urljoin(docs_url, src)
            # Use Playwright to check if the image is accessible
            img_response = page.goto(img_url)
            if img_response.status != 200:
                missing_images.append(f"Image not accessible: {img_url}")

        browser.close()

    assert not missing_images, f"The following images are missing or inaccessible:\n" + "\n".join(missing_images)