from fastapi import HTTPException
from server.cms.cms import make_strapi_request, get_nested
from server.api.security.crypto import verify_hash
import logging
# Set up logger
logger = logging.getLogger(__name__)


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
        logger.debug("Validating if the user has access to the file ...")

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
            logger.error("Got a status code of " + str(status_code) + " from strapi.")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if file_json_response["data"] == []:
            logger.error("The file does not exist.")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        # if the file exists and is is public, return True
        if get_nested(file_json_response,"access_public") == True:
            logger.debug("The file is public.")
            return file_json_response["data"][0]

        # else check if the user is on the list of users with access to the file
        if len(get_nested(file_json_response, f"{requested_access}_access_limited_to_users")) > 0:
            for user in get_nested(file_json_response, f"{requested_access}_access_limited_to_users"):
                if user_api_token and len(user_api_token)>1 and verify_hash(get_nested(user, "api_token"), user_api_token[32:]):
                    logger.debug("The user is on the list of users with access to the file.")
                    return file_json_response["data"][0]

        if len(get_nested(file_json_response, f"{requested_access}_access_limited_to_teams")) == 0 and len(get_nested(file_json_response, f"{requested_access}_access_limited_to_users")) == 0:
            logger.error("The file is not public and is not limited to any users or teams.")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if len(get_nested(file_json_response, f"{requested_access}_access_limited_to_teams")) == 0:
            logger.error("The file is not public and the user is not on the list of users with access to the file.")
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
            logger.error("Got a status code of " + str(status_code) + " from strapi.")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if len(user_json_response) == 0:
            logger.error("The user does not exist.")
            raise HTTPException(status_code=404, detail=request_refused_response_text)

        if len(user_json_response) > 1:
            logger.error("Found more than one user with the token.")
            raise HTTPException(status_code=500, detail="Found more than one user with your token. Please contact the administrator.")

        # check if the user team (based on token) is on the list of teams with access to the file
        for allowed_team in get_nested(file_json_response, f"{requested_access}_access_limited_to_teams"):
            # then check if the user in user_json_response is actually part of the team
            for user_team in get_nested(user_json_response, "teams"):
                if get_nested(user_team, "slug") == get_nested(allowed_team, "slug"):
                    logger.debug("The user is part of the team that has access to the file.")
                    return file_json_response["data"][0]

        logger.error("The user is not part of the team that has access to the file.")
        raise HTTPException(status_code=404, detail=request_refused_response_text)

    except HTTPException:
        raise

    except Exception:
        logger.error("Failed to validate the file access.")
        raise HTTPException(status_code=500, detail="Failed to validate the file access.")
