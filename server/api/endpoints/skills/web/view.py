from server.api.models.skills.web.skills_web_view import WebViewOutput
import logging
from fastapi import HTTPException
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import asyncio

# Set up logger
logger = logging.getLogger(__name__)

# Global variables for Playwright
playwright = None
browser = None

def simplify_html(soup):
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()

    # Extract text
    text = soup.get_text()

    # Break into lines and remove leading and trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # Break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # Drop blank lines
    text = '\n'.join(chunk for chunk in chunks if chunk)

    return text


async def open_webbrowser():
    global playwright, browser
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)

    logger.info("Web browser is ready")

# Add a shutdown function to clean up resources
async def close_webbrowser():
    global playwright, browser
    if browser:
        await browser.close()
    if playwright:
        await playwright.stop()


async def view(
    url: str
) -> WebViewOutput:
    """
    View a web page and return the content in markdown format.
    """
    global browser
    try:
        logger.debug(f"Viewing web page: {url}")

        # Ensure browser is initialized
        if browser is None:
            await open_webbrowser()

        # Use the existing browser to create a new page
        page = await browser.new_page()
        await page.goto(url)
        content = await page.content()
        await page.close()

        # Parse the HTML content with BeautifulSoup
        soup = BeautifulSoup(content, 'html.parser')

        # Create a simplified version of the HTML
        simplified_html = simplify_html(soup)

        # Extract basic information
        title = soup.title.string if soup.title else ""
        meta_description = soup.find('meta', attrs={'name': 'description'})
        description = meta_description['content'] if meta_description else ""

        # save simplified_html to a file
        with open("simplified_html.txt", "w") as f:
            f.write(simplified_html)

        # TODO: Extract keywords, authors, publisher, and published_date

        web_view_output: WebViewOutput = WebViewOutput(
            url=url,
            title=title,
            description=description,
            keywords=[],
            authors=[],
            publisher="",
            published_date=""
        )

        logger.debug(f"Successfully viewed web page: {url}")

        return web_view_output
    except Exception as e:
        logger.exception(f"An error occurred while viewing the web page")
        raise HTTPException(status_code=500, detail="An error occurred while viewing the web page")