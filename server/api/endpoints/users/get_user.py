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
from server.api.validation.validate_permissions import validate_permissions
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
            user_access = await validate_permissions(
                endpoint=f"/users/{username}",
                team_slug=team_slug,
                user_api_token=request_sender_api_token,
                user_username=username,
                user_password=password
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
                    if not verify_hash(hashed_text=get_nested(user, "api_token"), text=api_token[32:]):
                        status_code = 404
                        raise HTTPException(status_code=status_code, detail="Could not find the requested user.")

                # if password is given, check if the found user has the correct password
                if password:
                    if not verify_hash(hashed_text=get_nested(user, "password"), text=password):
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
                    "username": get_nested(user, "username"),
                    "email": decrypt(get_nested(user, "email")) if decrypt_data else get_nested(user, "email"),
                    "teams": [
                        {
                            "id": get_nested(team, "id"),
                            "name": get_nested(team, "name"),
                            "slug": get_nested(team, "slug")
                        } for team in get_nested(user, "teams")
                    ],
                    "profile_picture_url":  f"/v1/{team_slug}{get_nested(user, 'profile_image.file.url')}" if get_nested(user, 'profile_image') else None,
                    "balance_eur": get_nested(user, "balance"),
                    "mates_default_privacy_settings": {
                        "allowed_to_access_name": get_nested(user, "mate_privacy_config_default__allowed_to_access_name"),
                        "allowed_to_access_username": get_nested(user, "mate_privacy_config_default__allowed_to_access_username"),
                        "allowed_to_access_projects": get_nested(user, "mate_privacy_config_default__allowed_to_access_projects"),
                        "allowed_to_access_goals": get_nested(user, "mate_privacy_config_default__allowed_to_access_goals"),
                        "allowed_to_access_todos": get_nested(user, "mate_privacy_config_default__allowed_to_access_todos"),
                        "allowed_to_access_recent_topics": get_nested(user, "mate_privacy_config_default__allowed_to_access_recent_topics"),
                        "allowed_to_access_recent_emails": get_nested(user, "mate_privacy_config_default__allowed_to_access_recent_emails"),
                        "allowed_to_access_calendar": get_nested(user, "mate_privacy_config_default__allowed_to_access_calendar"),
                        "allowed_to_access_likes": get_nested(user, "mate_privacy_config_default__allowed_to_access_likes"),
                        "allowed_to_access_dislikes": get_nested(user, "mate_privacy_config_default__allowed_to_access_dislikes")
                    },
                    "mates_custom_settings":[
                        {
                            "id": get_nested(config, "id"),
                            "mate_username": get_nested(config, "mate.username"),
                            "team_slug": get_nested(config, "team.slug"),
                            "systemprompt": get_nested(config, "systemprompt"),
                            "llm_endpoint": "/v1/"+get_nested(config, "team.slug")+get_nested(config, "llm_endpoint") if get_nested(config, "llm_endpoint") else None,
                            "llm_model":get_nested(config, "llm_model"),
                            "skills": [
                                {
                                    "id": get_nested(skill, "id"),
                                    "name": get_nested(skill, "name"),
                                    "software": get_nested(skill, "software.name"),
                                    "api_endpoint": "/v1/"+get_nested(config, "team.slug")+"/skills/"+get_nested(skill, "software.slug")+"/"+get_nested(skill, "slug")
                                } for skill in get_nested(config, "skills")
                            ],
                            "allowed_to_access_user_name": get_nested(config, "allowed_to_access_user_name"),
                            "allowed_to_access_user_username": get_nested(config, "allowed_to_access_user_username"),
                            "allowed_to_access_user_projects": get_nested(config, "allowed_to_access_user_projects"),
                            "allowed_to_access_user_goals": get_nested(config, "allowed_to_access_user_goals"),
                            "allowed_to_access_user_todos": get_nested(config, "allowed_to_access_user_todos"),
                            "allowed_to_access_user_recent_topics": get_nested(config, "allowed_to_access_user_recent_topics"),
                            "allowed_to_access_user_recent_emails": get_nested(config, "allowed_to_access_user_recent_emails"),
                            "allowed_to_access_user_calendar": get_nested(config, "allowed_to_access_user_calendar"),
                            "allowed_to_access_user_likes": get_nested(config, "allowed_to_access_user_likes"),
                            "allowed_to_access_user_dislikes": get_nested(config, "allowed_to_access_user_dislikes")
                        } for config in get_nested(user, "mate_configs")["data"]
                    ],
                    "software_settings": decrypt(get_nested(user, "software_settings"),"dict") if decrypt_data else get_nested(user, "software_settings"),
                    "other_settings": decrypt(get_nested(user, "other_settings"),"dict") if decrypt_data else get_nested(user, "other_settings"),
                    "projects": [
                        {
                            "id": get_nested(project, "id"),
                            "name": get_nested(project, "name"),
                            "description": get_nested(project, "description")
                        } for project in get_nested(user, "projects")["data"]
                    ],
                    "likes": decrypt(get_nested(user, "likes"),"dict") if decrypt_data else get_nested(user, "likes"),
                    "dislikes": decrypt(get_nested(user, "dislikes"),"dict") if decrypt_data else get_nested(user, "dislikes"),
                    "goals": decrypt(get_nested(user, "goals"),"dict") if decrypt_data else get_nested(user, "goals"),
                    "todos": decrypt(get_nested(user, "todos"),"dict") if decrypt_data else get_nested(user, "todos"),
                    "recent_topics": decrypt(get_nested(user, "recent_topics"),"dict") if decrypt_data else get_nested(user, "recent_topics"),
                    "recent_emails": decrypt(get_nested(user, "recent_emails"),"dict") if decrypt_data else get_nested(user, "recent_emails"),
                    "calendar": decrypt(get_nested(user, "calendar"),"dict") if decrypt_data else get_nested(user, "calendar")
                } if user_access == "full_access" else {
                    "id": user["id"],
                    "username": get_nested(user, "username")
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