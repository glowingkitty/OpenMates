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
################

from typing import List, Optional, Union, Dict, Literal
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.models.files.files_upload import (
    FileUploadOutput
)


async def upload_file_processing(
        team_slug: str,
        user_api_token: str,
        file_name: str,
        data: bytes,
        access_public: bool,
        list_read_access_limited_to_team_slugs: Optional[List[str]] = None,
        list_write_access_limited_to_team_slugs: Optional[List[str]] = None,
        list_read_access_limited_to_user_usernames: Optional[List[str]] = None,
        list_write_access_limited_to_user_usernames: Optional[List[str]] = None
    ) -> FileUploadOutput:
    """
    Create a new file on the team
    """

    # TODO scale down the image file to 1024x1024 pixels max

    # TODO upload the file to the server
    # file_url = await make_strapi_request(
    #     method="POST",
    #     endpoint="uploaded-files",
    #     user_api_token=user_api_token,
    #     data={
    #         "data": {
    #             "file": data,
    #             "filename": file_name,
    #             "access_public": access_public,
    #             "read_access_limited_to_teams": list_read_access_limited_to_teams,
    #             "read_access_limited_to_users": list_read_access_limited_to_users,
    #             "write_access_limited_to_teams": list_write_access_limited_to_teams,
    #             "write_access_limited_to_users": list_write_access_limited_to_users
    #         }
    #     }
    # )

    # TODO return file url with team slug and file name, if successful

    json_response = {
        "url": f"/{team_slug}/uploads/{file_name}",
        "access_public": access_public,
        "read_access_limited_to_team_slugs": list_read_access_limited_to_team_slugs,
        "write_access_limited_to_team_slugs": list_write_access_limited_to_team_slugs,
        "read_access_limited_to_user_usernames": list_read_access_limited_to_user_usernames,
        "write_access_limited_to_user_usernames": list_write_access_limited_to_user_usernames
    }

    return JSONResponse(status_code=201, content=json_response)