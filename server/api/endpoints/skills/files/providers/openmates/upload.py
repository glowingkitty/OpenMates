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

from server.api import *
from server.cms.strapi_requests import make_strapi_request, upload_file_to_strapi

################

from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from fastapi import HTTPException
from typing import List, Optional
from server.api.security.crypto import encrypt_file
from urllib.parse import quote
from server.api.endpoints.skills.files.providers.openmates.generate_file_id import generate_file_id

async def upload(
    team_slug: str,
    file_name: str,
    file_data: bytes,
    folder_path: str,
    access_public: bool = False,
    api_token: Optional[str] = None,
    expiration_datetime: Optional[str] = None,
    read_access_limited_to_teams: Optional[List[int]] = None,
    read_access_limited_to_users: Optional[List[int]] = None,
    write_access_limited_to_teams: Optional[List[int]] = None,
    write_access_limited_to_users: Optional[List[int]] = None,
) -> FilesUploadOutput:
    """
    Upload a file to OpenMates
    """
    add_to_log(module_name="OpenMates | API | Files | Providers | OpenMates | Upload", state="start", color="yellow", hide_variables=True)

    # update the file name and make sure it is url safe
    file_name = quote(file_name.replace(" ", "_").lower(), safe='')

    # Encrypt the file using the api token + unique file id as key
    file_id = await generate_file_id()
    if access_public == False and api_token:
        key = f"{api_token}{file_id}"
        file_data = encrypt_file(file_data=file_data, key=key)

    # Upload the file to Strapi using file data
    file_info = await upload_file_to_strapi(file_data=file_data, file_name=file_name)
    file_info = file_info[0]

    # Create an entry in the 'uploaded-file' model
    entry_data = {
        "file": file_info["id"],
        "filename": file_name,
        "file_id": file_id,
        "access_public": access_public,
        "expiration_datetime": expiration_datetime,
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

    # Output url should be /v1/{team_slug}/skills/files/{folder_path}/{file_id}/{file_name}
    url = f"/v1/{team_slug}/skills/files/{folder_path}/{file_id}/{file_name}"

    return FilesUploadOutput(
        name=file_name,
        url=url,
        expiration_datetime=expiration_datetime,
        access_public=access_public,
        read_access_limited_to_teams=read_access_limited_to_teams,
        read_access_limited_to_users=read_access_limited_to_users,
        write_access_limited_to_teams=write_access_limited_to_teams,
        write_access_limited_to_users=write_access_limited_to_users
    )