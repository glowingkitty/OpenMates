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
################

from server.cms.cms import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from server.api.models.mates.mates_get_all import MatesGetAllOutput
from fastapi import HTTPException


async def get_mates(
        team_slug: str,
        page: int = 1,
        pageSize: int = 25
    ) -> MatesGetAllOutput:
    """
    Get a list of all AI team mates on a team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mates", state="start", color="yellow")
        add_to_log("Getting a list of all AI team mates in a team ...")

        fields = [
            "name",
            "username",
            "description"
        ]
        populate = [
            "profile_picture.file.url"
        ]
        filters = [
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_slug
            }
        ]
        status_code, json_response = await make_strapi_request(
            method='get',
            endpoint='mates',
            fields=fields,
            populate=populate,
            filters=filters,
            page=page,
            pageSize=pageSize,
            )

        if status_code == 200:
            mates = []
            for mate in json_response["data"]:
                mate_data = {
                    "id": get_nested(mate, "id"),
                    "name": get_nested(mate, "name"),
                    "username": get_nested(mate, "username"),
                    "description": get_nested(mate, "description"),
                    "profile_picture_url": f"/v1/{team_slug}{get_nested(mate, 'profile_picture.file.url')}" if get_nested(mate, "profile_picture") else None,
                }
                mates.append(mate_data)

            # if no mates, return a 404 error
            if len(mates) == 0:
                status_code = 404
                # Info: technically there are only no mates on the team, and the team might still exist,
                # but since its not allowed to have a team with 0 mates, we can make the assumption that the team does not exist
                json_response = {"detail": "Could not find a team with the requested team URL."}
            else:
                json_response["data"] = mates

        add_to_log("Successfully created a list of all mates in the requested team.", state="success")
        return JSONResponse(status_code=status_code, content=json_response)

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get all AI team mates in the team.")