################
# Default Imports
################
import sys
import os
import re
from fastapi import HTTPException

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
from server.cms.cms import make_strapi_request, delete_file_from_strapi
################

from server.api.models.skills.files.skills_files_delete import FilesDeleteOutput


async def delete(file_id: str) -> FilesDeleteOutput:
    """
    Delete a file from the OpenMates server
    """
    add_to_log(module_name="OpenMates | API | Files | Providers | OpenMates | Delete", state="start", color="yellow")

    add_to_log(f"Deleting file with ID {file_id} from OpenMates server...")

    # Fetch the file information
    status_code, json_response = await make_strapi_request(
        method='get',
        endpoint='uploaded-files',
        filters=[{"field": "file_id", "operator": "$eq", "value": file_id}],
        populate=["file.url"]
    )

    if status_code != 200 or not json_response.get("data") or len(json_response["data"]) == 0:
        add_to_log(f"No file found with the given file_id: {file_id}", state="error")
        raise HTTPException(status_code=404, detail="File not found")

    file_entry = json_response["data"][0]
    strapi_file_id = file_entry["attributes"]["file"]["data"]["id"]
    entry_id = file_entry["id"]

    # Delete file from Strapi media library
    delete_status = await delete_file_from_strapi(strapi_file_id)
    if not delete_status:
        add_to_log(f"Failed to delete file {strapi_file_id} from Strapi media library", state="error")
        raise HTTPException(status_code=500, detail="Failed to delete file from media library")

    # Delete entry from uploaded-files collection
    status_code, _ = await make_strapi_request(
        method='delete',
        endpoint=f'uploaded-files/{entry_id}'
    )

    if status_code != 200:
        add_to_log(f"Failed to delete entry {entry_id} from uploaded-files collection", state="error")
        raise HTTPException(status_code=500, detail="Failed to delete file entry")

    add_to_log(f"Successfully deleted file {file_id}", state="success")
    return FilesDeleteOutput(file_id=file_id, success=True)