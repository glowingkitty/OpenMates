################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
from server.cms.strapi_requests import make_strapi_request, upload_file_to_strapi

################

from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from fastapi import HTTPException
from typing import List


async def upload(
    provider: str,
    file_path: str,
    name: str,
    file_data: bytes,
    expiration_datetime: str,
    access_public: bool,
    read_access_limited_to_teams: List[int],
    read_access_limited_to_users: List[int],
    write_access_limited_to_teams: List[int],
    write_access_limited_to_users: List[int]
) -> FilesUploadOutput:
    """
    Upload a file to OpenMates
    """
    add_to_log(module_name="OpenMates | API | Files | Providers | OpenMates | Upload", state="start", color="yellow", hide_variables=True)

    # Upload the file to Strapi using file data
    file_info = await upload_file_to_strapi(file_data=file_data, file_name=name)

    # Create an entry in the 'uploaded-file' model
    entry_data = {
        "file": file_info["id"],
        "filename": name,
        "access_public": access_public,
        "read_access_limited_to_teams": read_access_limited_to_teams,
        "read_access_limited_to_users": read_access_limited_to_users,
        "write_access_limited_to_teams": write_access_limited_to_teams,
        "write_access_limited_to_users": write_access_limited_to_users
    }

    status_code, entry_info = await make_strapi_request(
        method='post',
        endpoint='uploaded-files',
        data={"data": entry_data}
    )

    if status_code != 200:
        add_to_log("Failed to create the uploaded file entry.", state="error")
        raise HTTPException(status_code=500, detail="Failed to create the uploaded file entry.")

    return FilesUploadOutput(
        name=name,
        url=file_info["url"],
        expiration_datetime=expiration_datetime,
        access_public=access_public,
        read_access_limited_to_teams=read_access_limited_to_teams,
        read_access_limited_to_users=read_access_limited_to_users,
        write_access_limited_to_teams=write_access_limited_to_teams,
        write_access_limited_to_users=write_access_limited_to_users
    )