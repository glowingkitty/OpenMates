from server.api.models.skills.web.skills_web_view import WebViewOutput
import logging
from fastapi import HTTPException
from bs4 import BeautifulSoup
import asyncio
import aiohttp
import os

# Set up logger
logger = logging.getLogger(__name__)

WEB_BROWSER_SECRET_KEY = os.getenv("WEB_BROWSER_SECRET_KEY")
WEB_BROWSER_PORT = os.getenv("WEB_BROWSER_PORT")


async def view(
    url: str
) -> WebViewOutput:
    """
    View a web page and return the content in markdown format.
    """
    try:
        logger.debug(f"Viewing web page: {url}")

        # Call the web_browser service
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://web_browser:{WEB_BROWSER_PORT}/view",
                params={"url": url},
                headers={"Authorization": f"Bearer {WEB_BROWSER_SECRET_KEY}"}
            ) as response:
                if response.status != 200:
                    raise HTTPException(status_code=response.status, detail="Failed to fetch content from web_browser")
                data = await response.json()

        # TODO: Extract keywords, authors, publisher, and published_date

        web_view_output: WebViewOutput = WebViewOutput(
            url=data.get("url", ""),
            title=data.get("title", "")
        )

        logger.debug(f"Successfully viewed web page: {url}")

        return web_view_output
    except Exception as e:
        logger.exception(f"An error occurred while viewing the web page")
        raise HTTPException(status_code=500, detail="An error occurred while viewing the web page")