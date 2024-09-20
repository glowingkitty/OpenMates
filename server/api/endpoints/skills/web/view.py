from server.api.models.skills.web.skills_web_view import WebViewOutput
import logging
from fastapi import HTTPException

# Set up logger
logger = logging.getLogger(__name__)

async def view(
    url: str
) -> WebViewOutput:
    """
    View a web page and return the content in markdown format.
    """
    try:
        logger.info(f"Viewing web page: {url}")
        # TODO: Implement the view function

        web_view_output: WebViewOutput = WebViewOutput(
            url=url,
            title="",
            description="",
            keywords=[],
            authors=[],
            publisher="",
            published_date=""
        )

        logger.info(f"Successfully viewed web page: {url}")

        return web_view_output
    except Exception as e:
        logger.error(f"Error viewing web page: {e}")
        raise HTTPException(status_code=500, detail="Error viewing web page")