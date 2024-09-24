from server.api.models.skills.files.skills_files_delete import FilesDeleteOutput
from server.cms.cms import make_strapi_request, delete_file_from_strapi
from fastapi import HTTPException

import logging

# Set up logger
logger = logging.getLogger(__name__)


async def delete(file_id: str) -> FilesDeleteOutput:
    """
    Delete a file from the OpenMates server
    """
    logger.debug(f"Deleting file with ID {file_id} from OpenMates server...")

    # Fetch the file information
    status_code, json_response = await make_strapi_request(
        method='get',
        endpoint='uploaded-files',
        filters=[{"field": "file_id", "operator": "$eq", "value": file_id}],
        populate=["file.url"]
    )

    if status_code != 200 or not json_response.get("data") or len(json_response["data"]) == 0:
        logger.error(f"No file found with the given file_id: {file_id}")
        raise HTTPException(status_code=404, detail="File not found")

    file_entry = json_response["data"][0]
    strapi_file_id = file_entry["attributes"]["file"]["data"]["id"]
    entry_id = file_entry["id"]

    # Delete file from Strapi media library
    delete_status = await delete_file_from_strapi(strapi_file_id)
    if not delete_status:
        logger.error(f"Failed to delete file {strapi_file_id} from Strapi media library")
        raise HTTPException(status_code=500, detail="Failed to delete file from media library")

    # Delete entry from uploaded-files collection
    status_code, _ = await make_strapi_request(
        method='delete',
        endpoint=f'uploaded-files/{entry_id}'
    )

    if status_code != 200:
        logger.error(f"Failed to delete entry {entry_id} from uploaded-files collection")
        raise HTTPException(status_code=500, detail="Failed to delete file entry")

    logger.debug(f"Successfully deleted file {file_id}")
    return FilesDeleteOutput(file_id=file_id, success=True)
