from server.api.models.skills.web.skills_web_read import WebReadOutput
import logging
from fastapi import HTTPException
import aiohttp
import os

# Set up logger
logger = logging.getLogger(__name__)

# TODO add processing in seperate docker container for every web request

async def read(
        url: str,
        include_images: bool = True,
        ai_optimization: bool = False
    ) -> WebReadOutput:
    """
    Read a web page and return the content in markdown format.
    """
    try:
        logger.debug(f"Reading web page with URL: {url}")

        # Call the web_browser service
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://web_browser:{os.getenv('WEB_BROWSER_PORT')}/read",
                json={"url": url, "include_images": include_images},
                headers={"Authorization": f"Bearer {os.getenv('WEB_BROWSER_SECRET_KEY')}"}
            ) as response:
                if response.status != 200:
                    raise HTTPException(status_code=response.status, detail="Failed to fetch content from web_browser")
                data = await response.json()

        # TODO: Add AI optimization (clean up markdown via LLM)

        web_read_output: WebReadOutput = WebReadOutput(
            url=data.get("url", ""),
            title=data.get("title", ""),
            content=data.get("text", ""),
            description=data.get("description", ""),
            keywords=data.get("keywords", []),
            authors=data.get("authors", []),
            publisher=data.get("publisher", ""),
            published_date=data.get("published_date", ""),
            html=data.get("html","")
        )

        logger.debug(f"Successfully read web page with URL: {url}")

        return web_read_output

    except Exception as e:
        logger.exception(f"An error occurred while reading the web page.")
        raise HTTPException(status_code=500, detail="An error occurred while reading the web page.")