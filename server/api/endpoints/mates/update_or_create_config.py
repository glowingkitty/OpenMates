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
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi import HTTPException
from server.api.security.crypto import verify_hash


async def update_or_create_config(
        mate: dict,
        team_slug: str,
        user_api_token: str,
        systemprompt: Optional[str] = None,
        llm_endpoint: Optional[str] = None,
        llm_model: Optional[str] = None,
        skills: Optional[List[int]] = None,
        allowed_to_access_user_name: Optional[bool] = None,
        allowed_to_access_user_username: Optional[bool] = None,
        allowed_to_access_user_projects: Optional[bool] = None,
        allowed_to_access_user_goals: Optional[bool] = None,
        allowed_to_access_user_todos: Optional[bool] = None,
        allowed_to_access_user_recent_topics: Optional[bool] = None
    ) -> dict:
    """
    Update or create a config for a specific AI team mate on the team
    """

    try:
        # Separate UUID and API token
        uid = user_api_token[:32]
        api_token = user_api_token[32:]

        config_id = None
        # search in the configs field of the mate for the config with the team and user
        if get_nested(mate, "configs"):
            for config in get_nested(mate, "configs"):
                if get_nested(config, "team.slug") == team_slug and verify_hash(get_nested(config, "user.api_token"), api_token):
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
                endpoint='user-accounts',
                filters=[{"field": "uid", "operator": "$eq", "value": uid}]
            )
            if status_code == 200 and json_response.get("data") and len(json_response["data"])==1:
                user = json_response["data"][0]
                if not verify_hash(get_nested(user, "api_token"), api_token):
                    raise HTTPException(status_code=403, detail="Invalid API token.")
            else:
                add_to_log("No user found with the given UID.", state="error")
                add_to_log(f"UID: {uid}", state="error")
                raise HTTPException(status_code=404, detail="No user found with the given UID.")

            # create a new config
            new_fields = {
                "team": team["id"],
                "user": user["id"],
                "mate": mate["id"],
            }
            if systemprompt != None:
                new_fields["systemprompt"] = systemprompt
            if skills != None:
                new_fields["skills"] = skills
            if allowed_to_access_user_name != None:
                new_fields["allowed_to_access_user_name"] = allowed_to_access_user_name
            if allowed_to_access_user_username != None:
                new_fields["allowed_to_access_user_username"] = allowed_to_access_user_username
            if allowed_to_access_user_projects != None:
                new_fields["allowed_to_access_user_projects"] = allowed_to_access_user_projects
            if allowed_to_access_user_goals != None:
                new_fields["allowed_to_access_user_goals"] = allowed_to_access_user_goals
            if allowed_to_access_user_todos != None:
                new_fields["allowed_to_access_user_todos"] = allowed_to_access_user_todos
            if allowed_to_access_user_recent_topics != None:
                new_fields["allowed_to_access_user_recent_topics"] = allowed_to_access_user_recent_topics

            status_code, json_response = await make_strapi_request(
                method='post',
                endpoint='mate-configs',
                data={"data":new_fields}
            )
            if status_code == 200 and json_response["data"]:
                config_id = get_nested(json_response, "id")
            else:
                raise HTTPException(status_code=500, detail="Failed to create a new config for the AI team mate.")

        # else update the existing config
        else:
            updated_fields = {}
            if systemprompt != None:
                updated_fields["systemprompt"] = systemprompt
            if llm_endpoint != None:
                updated_fields["llm_endpoint"] = llm_endpoint
            if llm_model != None:
                updated_fields["llm_model"] = llm_model
            if skills != None:
                updated_fields["skills"] = skills
            if allowed_to_access_user_name != None:
                updated_fields["allowed_to_access_user_name"] = allowed_to_access_user_name
            if allowed_to_access_user_username != None:
                updated_fields["allowed_to_access_user_username"] = allowed_to_access_user_username
            if allowed_to_access_user_projects != None:
                updated_fields["allowed_to_access_user_projects"] = allowed_to_access_user_projects
            if allowed_to_access_user_goals != None:
                updated_fields["allowed_to_access_user_goals"] = allowed_to_access_user_goals
            if allowed_to_access_user_todos != None:
                updated_fields["allowed_to_access_user_todos"] = allowed_to_access_user_todos
            if allowed_to_access_user_recent_topics != None:
                updated_fields["allowed_to_access_user_recent_topics"] = allowed_to_access_user_recent_topics

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