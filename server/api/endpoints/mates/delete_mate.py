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

from typing import Optional
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.cms.cms import make_strapi_request
from server.api.endpoints.mates.get_mate import get_mate

async def delete_mate(
        mate_username: str,
        team_slug: Optional[str] = None,
        user_api_token: Optional[str] = None
    ) -> JSONResponse:
    """
    Delete a specific AI team mate from the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Delete mate", state="start", color="yellow", hide_variables=True)
        add_to_log("Deleting a specific AI team mate from the team ...")

        # Get the mate to be deleted
        mate = await get_mate(
            team_slug=team_slug,
            mate_username=mate_username,
            user_api_token=user_api_token
        )

        # Delete the mate
        status_code, json_response = await make_strapi_request(
            method='delete',
            endpoint=f'mates/{mate["id"]}'
        )

        delete_mate = {
            "deleted_user": mate_username
        }

        if status_code == 200:
            add_to_log("Successfully deleted the AI team mate", state="success")
            return JSONResponse(status_code=200, content=delete_mate)
        else:
            add_to_log("Failed to delete the AI team mate.", state="error")
            raise HTTPException(status_code=500, detail="Failed to delete the AI team mate.")

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to delete the AI team mate.")