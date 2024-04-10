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
        "username",
        "description",
        "default_systemprompt"
        ]
        populate = [
            "profile_picture.url",
            "skills.name",
        ]
        # TODO implement filter for relationship to team
        # TODO add again seperate processing function to keep the api endpoint code short here
        # TODO return custom more condensed JSON output structure based on fastapi models
        response = await make_strapi_request(method='get', endpoint='mates', fields=fields, populate=populate)

        add_to_log("Successfully created a list of all mates in the requested team.", state="success")
        return response

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get a list of all mates in the team.", traceback=traceback.format_exc())
        return []