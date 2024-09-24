from server.api.models.skills.web.skills_web_read import WebReadOutput
import logging
from fastapi import HTTPException
import aiohttp
import os

# Set up logger
logger = logging.getLogger(__name__)

WEB_BROWSER_SECRET_KEY = os.getenv("WEB_BROWSER_SECRET_KEY")
WEB_BROWSER_PORT = os.getenv("WEB_BROWSER_PORT")


async def read(
        url: str,
        include_images: bool = True
    ) -> WebReadOutput:
    """
    Read a web page and return the content in markdown format.
    """
    try:
        logger.debug(f"Reading web page with URL: {url}")

        # Call the web_browser service
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://web_browser:{WEB_BROWSER_PORT}/read",
                params={"url": url},
                headers={"Authorization": f"Bearer {WEB_BROWSER_SECRET_KEY}"}
            ) as response:
                if response.status != 200:
                    raise HTTPException(status_code=response.status, detail="Failed to fetch content from web_browser")
                data = await response.json()

        web_read_output: WebReadOutput = WebReadOutput(
            url=data.get("url", ""),
            title=data.get("title", ""),
            content=data.get("text", ""),
            description=data.get("description", ""),
            keywords=data.get("keywords", []),
            authors=data.get("authors", []),
            publisher=data.get("publisher", ""),
            published_date=data.get("published_date", "")
        )

        logger.debug(f"Successfully read web page with URL: {url}")

        return web_read_output

    except Exception as e:
        logger.exception(f"An error occurred while reading the web page.")
        raise HTTPException(status_code=500, detail="An error occurred while reading the web page.")