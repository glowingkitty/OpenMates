from typing import List
import logging
from server.api.endpoints.apps.docs.providers.microsoft_word.create import create as create_microsoft_word
from server.api.models.apps.files.skills_files_upload import FilesUploadOutput

# Set up logger
logger = logging.getLogger(__name__)


async def create(
    team_slug: str,
    api_token: str,
    title: str,
    elements: List[dict]
) -> FilesUploadOutput:
    """
    Create a new document
    """
    logger.debug("Creating a new document ...")

    doc = await create_microsoft_word(
        team_slug=team_slug,
        api_token=api_token,
        title=title,
        elements=elements
    )

    return doc