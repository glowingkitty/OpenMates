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

from typing import List, Optional
from server.cms.strapi_requests import make_strapi_request
from fastapi import HTTPException


async def update_or_create_config(
        mate: dict,
        team_slug: str,
        user_api_token: str,
        systemprompt: Optional[str] = None,
        skills: Optional[List[int]] = None
    ) -> dict:
    """
    Update or create a config for a specific AI team mate on the team
    """
    
    try:
        config_id = None
        # search in the configs field of the mate for the config with the team and user
        if mate["attributes"]["configs"]:
            for config in mate["attributes"]["configs"]["data"]:
                if config["data"]["attributes"]["team"]["data"]["attributes"]["slug"] == team_slug and config["data"]["attributes"]["user"]["data"]["attributes"]["api_token"] == user_api_token:
                    config_id = config["id"]
                    break
    
        # if no config is found, create a new one
        if config_id == None:
            # get the team and its ID
            status_code, json_response = await make_strapi_request(
                method='get', 
                endpoint='teams', 
                filters=[{"field": "slug", "operator": "$eq", "value": team_slug}]
            )
            if status_code == 200 and json_response["data"]:
                if len(json_response["data"])==1:
                    team = json_response["data"][0]
                elif len(json_response["data"])>1:
                    add_to_log("More than one team found with the same URL.", state="error")
                    raise HTTPException(status_code=500, detail="More than one team found with the same URL.")

            else:
                add_to_log("No team found with the given URL.", state="error")
                raise HTTPException(status_code=404, detail="No team found with the given URL.")

            # get the user and its ID
            status_code, json_response = await make_strapi_request(
                method='get', 
                endpoint='users', 
                filters=[{"field": "api_token", "operator": "$eq", "value": user_api_token}]
            )
            if status_code == 200 and json_response:
                user = json_response[0]
            
            # create a new config
            new_fields = {
                "team": team["id"],
                "user": user["id"]
            }
            if systemprompt != None:
                new_fields["systemprompt"] = systemprompt
            if skills != None:
                new_fields["skills"] = skills

            status_code, json_response = await make_strapi_request(
                method='post', 
                endpoint='mate-configs', 
                data={"data":new_fields}
            )
            if status_code == 200 and json_response["data"]:
                config_id = json_response["data"]["id"]
            else:
                raise HTTPException(status_code=500, detail="Failed to create a new config for the AI team mate.")

        # else update the existing config
        else:
            updated_fields = {}
            if systemprompt != None:
                updated_fields["systemprompt"] = systemprompt
            if skills != None:
                updated_fields["skills"] = skills

            status_code, json_response = await make_strapi_request(
                method='put', 
                endpoint='mate-configs/'+str(config_id), 
                data={"data":updated_fields}
            )
            if status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to update the config for the AI team mate.")

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to update or create a config for the AI team mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to update or create a config for the AI team mate.")

        