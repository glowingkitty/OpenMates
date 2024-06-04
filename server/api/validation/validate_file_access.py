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

from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request
from server.api.security.crypto import verify_hash


async def validate_file_access(
        filename: str,
        team_slug: str,
        user_api_token: str,
        scope: str = "uploads:read"
    ) -> dict:
    """
    Validate if the user has access to the file (and if its uploaded)
    """
    try:
        add_to_log(module_name="OpenMates | API | Validate file Access", state="start", color="yellow", hide_variables=True)
        add_to_log("Validating if the user has access to the file ...")

        request_refused_response_text = f"The file '/v1/{team_slug}/uploads/{filename}' does not exist or you do not have access to it."

        # check for requested access
        if scope == "uploads:read":
            requested_access = "read"
        elif scope == "uploads:write":
            requested_access = "write"

        # try to get the file from strapi
        fields = [
            "access_public",
            "filename"
        ]
        populate = [
            "file.url",
            f"{requested_access}_access_limited_to_teams.slug",
            f"{requested_access}_access_limited_to_users.username",
            f"{requested_access}_access_limited_to_users.api_token"
        ]
        filters = [
            {
                "field": "filename",
                "operator": "$eq",
                "value": filename
            }
        ]
        status_code, file_json_response = await make_strapi_request(
            method='get',
            endpoint='uploaded-files',
            fields=fields,
            populate=populate,
            filters=filters
            )

        # if it fails, return a http response error that says either the file doesn't exist or you don't have access to it
        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate file Access")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if file_json_response["data"] == []:
            add_to_log("The file does not exist.", module_name="OpenMates | API | Validate file Access")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        # if the file exists and is is public, return True
        if file_json_response["data"][0]["attributes"]["access_public"] == True:
            add_to_log("The file is public.", module_name="OpenMates | API | Validate file Access", state="success")
            return file_json_response["data"][0]

        # else check if the user is on the list of users with access to the file
        if len(file_json_response["data"][0]["attributes"][f"{requested_access}_access_limited_to_users"]["data"]) > 0:
            for user in file_json_response["data"][0]["attributes"][f"{requested_access}_access_limited_to_users"]["data"]:
                if user_api_token and len(user_api_token)>1 and verify_hash(user["attributes"]["api_token"], user_api_token[32:]):
                    add_to_log("The user is on the list of users with access to the file.", module_name="OpenMates | API | Validate file Access", state="success")
                    return file_json_response["data"][0]

        if len(file_json_response["data"][0]["attributes"][f"{requested_access}_access_limited_to_teams"]["data"]) == 0 and len(file_json_response["data"][0]["attributes"][f"{requested_access}_access_limited_to_users"]["data"]) == 0:
            add_to_log("The file is not public and is not limited to any users or teams.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if len(file_json_response["data"][0]["attributes"][f"{requested_access}_access_limited_to_teams"]["data"]) == 0:
            add_to_log("The file is not public and the user is not on the list of users with access to the file.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        # else get the user team based on the token
        fields = [
            "api_token"
        ]
        populate = [
            "teams.slug"
        ]
        filters = [
            {
                "field": "api_token",
                "operator": "$eq",
                "value": user_api_token
            },
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_slug
            }
        ]
        status_code, user_json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=fields,
            populate=populate,
            filters=filters
            )

        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if len(user_json_response) == 0:
            add_to_log("The user does not exist.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if len(user_json_response) > 1:
            add_to_log("Found more than one user with the token.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=500, detail="Found more than one user with your token. Please contact the administrator.")

        # check if the user team (based on token) is on the list of teams with access to the file
        for allowed_team in file_json_response["data"][0]["attributes"][f"{requested_access}_access_limited_to_teams"]["data"]:
            # then check if the user in user_json_response is actually part of the team
            for user_team in user_json_response[0]["teams"]:
                if user_team["slug"] == allowed_team["attributes"]["slug"]:
                    add_to_log("The user is part of the team that has access to the file.", module_name="OpenMates | API | Validate file Access", state="success")
                    return file_json_response["data"][0]

        add_to_log("The user is not part of the team that has access to the file.", module_name="OpenMates | API | Validate file Access", state="error")
        raise HTTPException(status_code=404, detail=request_refused_response_text)

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to validate the file access.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the file access.")