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
from server.api.security.crypto import hashing_sha256


async def get_user(
        team_slug: Optional[str] = None,
        request_sender_api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_token: Optional[str] = None,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "dict"] = "JSONResponse"
    ) -> Union[JSONResponse, Dict, HTTPException]:
    """
    Get a specific user.
    """
    try:
        add_to_log(module_name="OpenMates | API | Get user", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a specific user ...")

        # TODO can I simplify the function? for example are all parameters needed?

        if not api_token and not (username and password):
            raise ValueError("You need to provide either an api token or username and password.")

        # check if the user is a server or team admin
        if request_sender_api_token:
            user_access = await validate_user_data_access(
                username=username,
                request_team_slug=team_slug,
                request_sender_api_token=request_sender_api_token,
                request_endpoint="get_one_user"
            )
        else:
            user_access = "basic_access"

        fields = {
            "full_access":[
                "username",
                "email",
                "api_token",
                "balance",
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
        if api_token:
            filters.append({
                "field": "api_token",
                "operator": "$eq",
                "value": hashing_sha256(api_token)
            })
        if username and password:
            filters.append({
                "field": "username",
                "operator": "$eq",
                "value": username
            })
            # filters.append({
            #     "field": "password",
            #     "operator": "$eq",
            #     "value": hashing_argon2(password)
            # })
            # TODO this won't work. Instead I need to check for every found user, if the password is correct via ph.verify(password, hashed_password)

        status_code, json_response = await make_strapi_request(
            method="get",
            endpoint="users",
            filters=filters,
            fields=fields[user_access],
            populate=populate[user_access]
        )

        if status_code == 200:
            # make sure there is only one user with the requested username
            user = {}
            users = json_response

            add_to_log(f"Found {len(users)} users with the requested username.")

            if len(users) == 0:
                status_code = 404
                json_response = {"detail": "Could not find the requested user."}
            elif len(users) > 1:
                status_code = 404
                json_response = {"detail": "There are multiple users with the requested username."}
            else:
                user = users[0]

                # return the unprocessed json if requested
                if output_raw_data:
                    if output_format == "JSONResponse":
                        return JSONResponse(status_code=status_code, content=user)
                    else:
                        return user

                user = {
                    "id": user["id"],
                    "username": user["username"],
                    "email": user["email"],
                    "teams": [
                        {
                            "id": team["id"],
                            "name": team["name"],
                            "slug": team["slug"]
                        } for team in user["teams"]
                    ],
                    "profile_picture_url":  f"/{team_slug}{get_nested(user, ['profile_image', 'file','url'])}" if get_nested(user, ['profile_image']) else None,
                    "balance_eur": user["balance"],
                    "mates_default_privacy_settings": {
                        "allowed_to_access_name": user["mate_privacy_config_default__allowed_to_access_name"],
                        "allowed_to_access_username": user["mate_privacy_config_default__allowed_to_access_username"],
                        "allowed_to_access_projects": user["mate_privacy_config_default__allowed_to_access_projects"],
                        "allowed_to_access_goals": user["mate_privacy_config_default__allowed_to_access_goals"],
                        "allowed_to_access_todos": user["mate_privacy_config_default__allowed_to_access_todos"],
                        "allowed_to_access_recent_topics": user["mate_privacy_config_default__allowed_to_access_recent_topics"],
                        "allowed_to_access_recent_emails": user["mate_privacy_config_default__allowed_to_access_recent_emails"],
                        "allowed_to_access_calendar": user["mate_privacy_config_default__allowed_to_access_calendar"],
                        "allowed_to_access_likes": user["mate_privacy_config_default__allowed_to_access_likes"],
                        "allowed_to_access_dislikes": user["mate_privacy_config_default__allowed_to_access_dislikes"]
                    },
                    "mates_custom_settings":[
                        {
                            "mate_username": config["mate"]["username"],
                            "team_slug": config["team"]["slug"],
                            "systemprompt": config["systemprompt"],
                            "skills": [
                                {
                                    "id": skill["id"],
                                    "name": skill["name"],
                                    "software": skill["software"]["name"],
                                    "api_endpoint": f"/{team_slug}/skills/{skill['software']['slug']}/{skill['slug']}"
                                } for skill in config["skills"]
                            ],
                            "allowed_to_access_user_name": config["allowed_to_access_user_name"],
                            "allowed_to_access_user_username": config["allowed_to_access_user_username"],
                            "allowed_to_access_user_projects": config["allowed_to_access_user_projects"],
                            "allowed_to_access_user_goals": config["allowed_to_access_user_goals"],
                            "allowed_to_access_user_todos": config["allowed_to_access_user_todos"],
                            "allowed_to_access_user_recent_topics": config["allowed_to_access_user_recent_topics"],
                            "allowed_to_access_user_recent_emails": config["allowed_to_access_user_recent_emails"],
                            "allowed_to_access_user_calendar": config["allowed_to_access_user_calendar"],
                            "allowed_to_access_user_likes": config["allowed_to_access_user_likes"],
                            "allowed_to_access_user_dislikes": config["allowed_to_access_user_dislikes"]
                        } for config in user["mate_configs"]
                    ],
                    "software_settings": user["software_settings"],
                    "other_settings": user["other_settings"],
                    "projects": [
                        {
                            "id": project["id"],
                            "name": project["name"],
                            "description": project["description"]
                        } for project in user["projects"]
                    ],
                    "likes": user["likes"],
                    "dislikes": user["dislikes"],
                    "goals": user["goals"],
                    "todos": user["todos"],
                    "recent_topics": user["recent_topics"],
                    "recent_emails": user["recent_emails"],
                    "calendar": user["calendar"]
                } if user_access == "full_access" else {
                    "id": user["id"],
                    "username": user["username"]
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