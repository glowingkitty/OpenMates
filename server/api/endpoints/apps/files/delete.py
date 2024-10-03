from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from server.api.endpoints.apps.files.providers.openmates.delete import delete as openmates_delete
from server.api.models.apps.files.skills_files_delete import FilesDeleteOutput

import logging

# Set up logger
logger = logging.getLogger(__name__)


async def delete(
    provider: str,
    file_path: str
) -> FilesDeleteOutput:
    """
    Delete a file from a provider
    """
    logger.debug("Deleting a file from a provider ...")

    if provider == "dropbox":
        # return await dropbox_delete(file_path)
        # TODO: implement dropbox delete
        pass
    else:
        try:
            file_id = file_path.split("/")[-2]
        except Exception as e:
            logger.error(f"Error extracting file_id from file_path: {e}")
            raise HTTPException(status_code=400, detail="Invalid file path")
        return await openmates_delete(
            file_id=file_id
        )