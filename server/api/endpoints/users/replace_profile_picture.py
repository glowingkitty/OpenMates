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
from server.api.endpoints.users.get_user import get_user
from server.api.models.users.users_replace_profile_picture import UsersReplaceProfilePictureOutput
from server.api.validation.validate_permissions import validate_permissions
import time
import base64


async def replace_profile_picture_processing(
        team_slug: str,
        api_token: str,
        username: str,
        user_access: str,
        file:bytes,
        visibility: Literal["public", "team", "server"]
    ) -> UsersReplaceProfilePictureOutput:
    """
    Replace the profile picture of a user
    """

    # TODO this function is confusing and incomplete.
    # REWRITE

    error_message = "User not found. Either the username is wrong, the team slug is wrong or the user is not part of the team or you don't have the permission to access this user."

    if user_access == "full_access":
        add_to_log("User has full access to the user data.")

        # give file a name based on team_slug, username and unix timestamp
        filename = f"{team_slug}_{username}_{int(time.time())}.jpeg"

        # if the visibility is team, add the team to the files 'read_access_limited_to_teams'
        read_access_limited_to_teams = []
        if visibility == "team":
            # get the team from strapi
            team = await get_team(team_slug=team_slug)
            read_access_limited_to_teams.append(team)

            # status_code, json_response = await make_strapi_request(
            #     method='get',
            #     endpoint='teams',
            #     filters=[{"field": "slug", "operator": "$eq", "value": team_slug}]
            # )
            # if status_code == 200 and json_response["data"]:
            #     if len(json_response["data"])==1:
            #         team = json_response["data"][0]
            #         read_access_limited_to_teams.append(team)
            #     elif len(json_response["data"])>1:
            #         add_to_log("More than one team found with the same URL.", state="error")
            #         raise HTTPException(status_code=500, detail="More than one team found with the same URL.")

            # else:
            #     add_to_log("No team found with the given URL.", state="error")
            #     raise HTTPException(status_code=404, detail="No team found with the given URL.")

        # limit the write access to the user (get the user from the strapi request)
        # user = await get_user(
        #     team_slug=team_slug,
        #     username=username,
        #     api_token=api_token
        # )
        user = await get_user(
            team_slug=team_slug,
            request_sender_api_token=api_token,
            username=username,
            api_token=api_token,
            output_raw_data=True,
            output_format="dict"
        )
        write_access_limited_to_users = [user]

        # upload the file to the strapi server
        uploaded_file = await upload_file(
            filename=filename,
            data=file
        )

        # TODO create a new entry in the files model
        uploaded_file_custom_model_entry = await create_uploaded_file(
            filename=filename,
            file=uploaded_file,
            access_public= visibility == "public",
            read_access_limited_to_teams=read_access_limited_to_teams,
            write_access_limited_to_users=write_access_limited_to_users
        )
        
        
        # TODO replace profile picture
        
        
        # TODO delete old profile picture

        return {
            "profile_picture_url": "/v1/ai-sales-team/uploads/johnd_new_image.jpeg"
        }

    else:
        add_to_log("User has no access to change the profile picture.")
        raise HTTPException(status_code=403, detail=error_message)