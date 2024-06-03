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
from server.api.validation.validate_user_data_access import validate_user_data_access
from server.api.security.crypto import verify_hash, decrypt


async def get_user(
        team_slug: Optional[str] = None,
        request_sender_api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_token: Optional[str] = None,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "dict"] = "JSONResponse",
        decrypt_data: bool = False
    ) -> Union[JSONResponse, Dict, HTTPException]:
    """
    Get a specific user.
    """
    try:
        add_to_log(module_name="OpenMates | API | Get user", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a specific user ...")

        # TODO clean up function, make it simpler and easier to read

        if not api_token and not (username and password):
            raise ValueError("You need to provide either an api token or username and password.")

        # check if the user is a server or team admin
        if request_sender_api_token or (username and password):
            # TODO this means the database is asked twice for the user data, inefficient...
            user_access = await validate_user_data_access(
                request_team_slug=team_slug,
                token=request_sender_api_token,
                username=username,
                password=password,
                request_endpoint="get_one_user"
            )
        else:
            user_access = "basic_access"

        fields = {
            "full_access":[
                "username",
                "email",
                "api_token",
                "password",
                "balance",
                "mate_default_llm_endpoint",
                "mate_privacy_config_default__allowed_to_access_name",
                "mate_privacy_config_default__allowed_to_access_username",
                "mate_privacy_config_default__allowed_to_access_projects",
                "mate_privacy_config_default__allowed_to_access_goals",
                "mate_privacy_config_default__allowed_to_access_todos",
                "mate_privacy_config_default__allowed_to_access_recent_topics",
                "mate_privacy_config_default__allowed_to_access_recent_emails",
                "mate_privacy_config_default__allowed_to_access_calendar",
                "mate_privacy_config_default__allowed_to_access_likes",
                "mate_privacy_config_default__allowed_to_access_dislikes",
                "software_settings",
                "other_settings",
                "goals",
                "todos",
                "recent_topics",
                "recent_emails",
                "calendar",
                "likes",
                "dislikes"
            ],
            "basic_access":[
                "username"
            ]
        }
        populate = {
            "full_access":[
                "profile_image.file.url",
                "teams.slug",
                "projects.name",
                "mate_configs.systemprompt",
                "mate_configs.mate.username",
                "mate_configs.team.slug",
                "mate_configs.ai_endpoint",
                "mate_configs.ai_model",
                "mate_configs.skills.name",
                "mate_configs.skills.description",
                "mate_configs.skills.slug",
                "mate_configs.skills.software.name",
                "mate_configs.skills.software.slug",
                "mate_configs.allowed_to_access_user_name",
                "mate_configs.allowed_to_access_user_username",
                "mate_configs.allowed_to_access_user_projects",
                "mate_configs.allowed_to_access_user_goals",
                "mate_configs.allowed_to_access_user_todos",
                "mate_configs.allowed_to_access_user_recent_topics",
                "mate_configs.allowed_to_access_user_recent_emails",
                "mate_configs.allowed_to_access_user_calendar",
                "mate_configs.allowed_to_access_user_likes",
                "mate_configs.allowed_to_access_user_dislikes"
            ],
            "basic_access":[]
        }
        filters = []
        if username:
            filters.append({
                "field": "username",
                "operator": "$eq",
                "value": username
            })

        status_code, json_response = await make_strapi_request(
            method="get",
            endpoint="user-accounts",
            filters=filters,
            fields=fields[user_access],
            populate=populate[user_access]
        )

        if status_code == 200:
            # make sure there is only one user with the requested username
            user = {}
            users = json_response["data"]

            add_to_log(f"Found {len(users)} users with the requested username.")

            if len(users) == 0:
                status_code = 404
                json_response = {"detail": "Could not find the requested user."}
            elif len(users) > 1:
                status_code = 404
                json_response = {"detail": "There are multiple users with the requested username."}
            else:
                user = users[0]

                if api_token:
                    if not verify_hash(hashed_text=user["attributes"]["api_token"], text=api_token[32:]):
                        status_code = 404
                        raise HTTPException(status_code=status_code, detail="Could not find the requested user.")

                # if password is given, check if the found user has the correct password
                if password:
                    if not verify_hash(hashed_text=user["attributes"]["password"], text=password):
                        status_code = 404
                        raise HTTPException(status_code=status_code, detail="Could not find the requested user.")

                # return the unprocessed json if requested
                if output_raw_data:
                    if output_format == "JSONResponse":
                        return JSONResponse(status_code=status_code, content=user)
                    else:
                        return user

                user = {
                    "id": user["id"],
                    "username": user["attributes"]["username"],
                    "email": decrypt(user["attributes"]["email"]) if decrypt_data else user["attributes"]["email"],
                    "teams": [
                        {
                            "id": team["id"],
                            "name": team["attributes"]["name"],
                            "slug": team["attributes"]["slug"]
                        } for team in user["attributes"]["teams"]["data"]
                    ],
                    "profile_picture_url":  f"/v1/{team_slug}{get_nested(user, ['profile_image', 'file','url'])}" if get_nested(user, ['profile_image']) else None,
                    "balance_eur": user["attributes"]["balance"],
                    "mates_default_privacy_settings": {
                        "allowed_to_access_name": user["attributes"]["mate_privacy_config_default__allowed_to_access_name"],
                        "allowed_to_access_username": user["attributes"]["mate_privacy_config_default__allowed_to_access_username"],
                        "allowed_to_access_projects": user["attributes"]["mate_privacy_config_default__allowed_to_access_projects"],
                        "allowed_to_access_goals": user["attributes"]["mate_privacy_config_default__allowed_to_access_goals"],
                        "allowed_to_access_todos": user["attributes"]["mate_privacy_config_default__allowed_to_access_todos"],
                        "allowed_to_access_recent_topics": user["attributes"]["mate_privacy_config_default__allowed_to_access_recent_topics"],
                        "allowed_to_access_recent_emails": user["attributes"]["mate_privacy_config_default__allowed_to_access_recent_emails"],
                        "allowed_to_access_calendar": user["attributes"]["mate_privacy_config_default__allowed_to_access_calendar"],
                        "allowed_to_access_likes": user["attributes"]["mate_privacy_config_default__allowed_to_access_likes"],
                        "allowed_to_access_dislikes": user["attributes"]["mate_privacy_config_default__allowed_to_access_dislikes"]
                    },
                    "mates_custom_settings":[
                        {
                            "id": config["id"],
                            "mate_username": config["attributes"]["mate"]["data"]["attributes"]["username"],
                            "team_slug": config["attributes"]["team"]["data"]["attributes"]["slug"],
                            "systemprompt": config["attributes"]["systemprompt"],
                            "llm_endpoint": "/v1/"+config["attributes"]["team"]["data"]["attributes"]["slug"]+config["attributes"]["llm_endpoint"] if config["attributes"]["llm_endpoint"] else None,
                            "llm_model":config["attributes"]["llm_model"],
                            "skills": [
                                {
                                    "id": skill["id"],
                                    "name": skill["attributes"]["name"],
                                    "software": skill["attributes"]["software"]["data"]["attributes"]["name"],
                                    "api_endpoint": "/v1/"+config["attributes"]["team"]["data"]["attributes"]["slug"]+"/skills/"+skill['attributes']['software']['data']['attributes']['slug']+"/"+skill['attributes']['slug']
                                } for skill in config["attributes"]["skills"]["data"]
                            ],
                            "allowed_to_access_user_name": config["attributes"]["allowed_to_access_user_name"],
                            "allowed_to_access_user_username": config["attributes"]["allowed_to_access_user_username"],
                            "allowed_to_access_user_projects": config["attributes"]["allowed_to_access_user_projects"],
                            "allowed_to_access_user_goals": config["attributes"]["allowed_to_access_user_goals"],
                            "allowed_to_access_user_todos": config["attributes"]["allowed_to_access_user_todos"],
                            "allowed_to_access_user_recent_topics": config["attributes"]["allowed_to_access_user_recent_topics"],
                            "allowed_to_access_user_recent_emails": config["attributes"]["allowed_to_access_user_recent_emails"],
                            "allowed_to_access_user_calendar": config["attributes"]["allowed_to_access_user_calendar"],
                            "allowed_to_access_user_likes": config["attributes"]["allowed_to_access_user_likes"],
                            "allowed_to_access_user_dislikes": config["attributes"]["allowed_to_access_user_dislikes"]
                        } for config in user["attributes"]["mate_configs"]["data"]
                    ],
                    "software_settings": decrypt(user["attributes"]["software_settings"],"dict") if decrypt_data else user["attributes"]["software_settings"],
                    "other_settings": decrypt(user["attributes"]["other_settings"],"dict") if decrypt_data else user["attributes"]["other_settings"],
                    "projects": [
                        {
                            "id": project["id"],
                            "name": project["attributes"]["name"],
                            "description": project["attributes"]["description"]
                        } for project in user["attributes"]["projects"]["data"]
                    ],
                    "likes": decrypt(user["attributes"]["likes"],"dict") if decrypt_data else user["attributes"]["likes"],
                    "dislikes": decrypt(user["attributes"]["dislikes"],"dict") if decrypt_data else user["attributes"]["dislikes"],
                    "goals": decrypt(user["attributes"]["goals"],"dict") if decrypt_data else user["attributes"]["goals"],
                    "todos": decrypt(user["attributes"]["todos"],"dict") if decrypt_data else user["attributes"]["todos"],
                    "recent_topics": decrypt(user["attributes"]["recent_topics"],"dict") if decrypt_data else user["attributes"]["recent_topics"],
                    "recent_emails": decrypt(user["attributes"]["recent_emails"],"dict") if decrypt_data else user["attributes"]["recent_emails"],
                    "calendar": decrypt(user["attributes"]["calendar"],"dict") if decrypt_data else user["attributes"]["calendar"]
                } if user_access == "full_access" else {
                    "id": user["id"],
                    "username": user["attributes"]["username"]
                }

                json_response = user


        add_to_log("Successfully got the user.", state="success")

        if output_format == "JSONResponse":
            return JSONResponse(status_code=status_code, content=json_response)
        else:
            return json_response

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the user.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the user.")