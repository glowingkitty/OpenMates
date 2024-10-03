from fastapi.responses import StreamingResponse
from server.api.endpoints.apps.files.providers.openmates.download import download as openmates_download

import logging

# Set up logger
logger = logging.getLogger(__name__)


async def download(
    provider: str,
    api_token: str,
    file_path: str
) -> StreamingResponse:
    """
    Download a file from a provider
    """
    logger.debug("Downloading a file from a provider ...")

    if provider == "dropbox":
        # return await dropbox_download(file_path)
        # TODO: implement dropbox download
        pass
    else:
        return await openmates_download(
            api_token=api_token,
            file_path=file_path
        )