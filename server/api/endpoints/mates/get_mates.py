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

from typing import List
from server.api.models.mates import Mate
from server.cms.strapi_requests import make_strapi_request


async def get_mates_processing(team_url: str) -> List[Mate]:
    """
    Get a list of all AI team mates on a team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mates", state="start", color="yellow")
        add_to_log("Getting a list of all AI team mates in a team ...")

        fields = [
            "name",
            "slug",
            "description",
            "default_systemprompt"
        ]
        populate = [
            "profile_picture.url",
            "skills.name",
        ]
        filters = [
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_url
            }
        ]
        # TODO return custom more condensed JSON output structure based on fastapi models
        response = await make_strapi_request(
            method='get', 
            endpoint='mates', 
            fields=fields, 
            populate=populate, 
            filters=filters
            )

        add_to_log("Successfully created a list of all mates in the requested team.", state="success")
        return response

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get a list of all mates in the team.", traceback=traceback.format_exc())
        return []