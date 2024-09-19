from typing import Optional
from server.cms.cms import make_strapi_request, get_nested
from fastapi import HTTPException
from server.api.security.crypto import verify_hash, decrypt
from server.api.models.users.users_get_one import User, DefaultPrivacySettings, MateConfig
from server.api.models.teams.teams_get_one import Team
from server.api.models.projects.projects_get_one import Project
from server.api.models.skills.skills_get_one import Skill
import logging

# Set up logger
logger = logging.getLogger(__name__)


async def get_user(
        user_id: str,
        user_access: str,
        team_slug: Optional[str] = None,
        username: Optional[str] = None
    ) -> User:
    """
    Get a specific user.
    """
    try:
        if not user_id and not username:
            raise HTTPException(status_code=400, detail="You need to provide either an api token or username.")

        fields = {
            "full_access":[
                "username",
                "email",
                "api_token",
                "password",
                "balance_credits",
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
                "other_settings",
                "is_server_admin",
                "goals",
                "recent_topics",
                "likes",
                "dislikes",
                "uid"
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
        filters = [
            {"field": "username", "operator": "$eq", "value": username}
        ] if username else [
            {"field": "uid", "operator": "$eq", "value": user_id}
        ]

        status_code, json_response = await make_strapi_request(
            method="get",
            endpoint="user-accounts",
            filters=filters,
            fields=fields[user_access],
            populate=populate[user_access]
        )

        if status_code != 200 or not json_response["data"]:
            raise HTTPException(status_code=404, detail="Could not find the requested user.")

        user = json_response["data"][0]

        return User(
            id=get_nested(user, "uid"),
            username=get_nested(user, "username"),
            is_server_admin=get_nested(user, "is_server_admin"),
            teams=[
                Team(
                    id=get_nested(team, "id"),
                    name=get_nested(team, "name"),
                    slug=get_nested(team, "slug")
                ) for team in get_nested(user, "teams")
            ] if get_nested(user, "teams") else [],
            profile_picture_url=f"/v1/{team_slug}{get_nested(user, 'profile_image.file.url')}" if get_nested(user, 'profile_image') else None,
            balance_credits=get_nested(user, "balance_credits"),
            mates_default_privacy_settings=DefaultPrivacySettings(
                allowed_to_access_name=get_nested(user, "mate_privacy_config_default__allowed_to_access_name"),
                allowed_to_access_username=get_nested(user, "mate_privacy_config_default__allowed_to_access_username"),
                allowed_to_access_projects=get_nested(user, "mate_privacy_config_default__allowed_to_access_projects"),
                allowed_to_access_goals=get_nested(user, "mate_privacy_config_default__allowed_to_access_goals"),
                allowed_to_access_todos=get_nested(user, "mate_privacy_config_default__allowed_to_access_todos"),
                allowed_to_access_recent_topics=get_nested(user, "mate_privacy_config_default__allowed_to_access_recent_topics"),
                allowed_to_access_recent_emails=get_nested(user, "mate_privacy_config_default__allowed_to_access_recent_emails"),
                allowed_to_access_calendar=get_nested(user, "mate_privacy_config_default__allowed_to_access_calendar"),
                allowed_to_access_likes=get_nested(user, "mate_privacy_config_default__allowed_to_access_likes"),
                allowed_to_access_dislikes=get_nested(user, "mate_privacy_config_default__allowed_to_access_dislikes")
            ),
            mates_custom_settings=[
                MateConfig(
                    id=get_nested(config, "id"),
                    mate_username=get_nested(config, "mate.username"),
                    team_slug=get_nested(config, "team.slug"),
                    systemprompt=get_nested(config, "systemprompt"),
                    llm_endpoint="/v1/"+get_nested(config, "team.slug")+get_nested(config, "llm_endpoint") if get_nested(config, "llm_endpoint") else None,
                    llm_model=get_nested(config, "llm_model"),
                    skills=[
                        Skill(
                            id=get_nested(skill, "id"),
                            name=get_nested(skill, "name"),
                            software=get_nested(skill, "software.name"),
                            api_endpoint="/v1/"+get_nested(config, "team.slug")+"/skills/"+get_nested(skill, "software.slug")+"/"+get_nested(skill, "slug")
                        ) for skill in get_nested(config, "skills")
                    ],
                    allowed_to_access_user_name=get_nested(config, "allowed_to_access_user_name"),
                    allowed_to_access_user_username=get_nested(config, "allowed_to_access_user_username"),
                    allowed_to_access_user_projects=get_nested(config, "allowed_to_access_user_projects"),
                    allowed_to_access_user_goals=get_nested(config, "allowed_to_access_user_goals"),
                    allowed_to_access_user_todos=get_nested(config, "allowed_to_access_user_todos"),
                    allowed_to_access_user_recent_topics=get_nested(config, "allowed_to_access_user_recent_topics"),
                    allowed_to_access_user_recent_emails=get_nested(config, "allowed_to_access_user_recent_emails"),
                    allowed_to_access_user_calendar=get_nested(config, "allowed_to_access_user_calendar"),
                    allowed_to_access_user_likes=get_nested(config, "allowed_to_access_user_likes"),
                    allowed_to_access_user_dislikes=get_nested(config, "allowed_to_access_user_dislikes")
                ) for config in get_nested(user, "mate_configs") if get_nested(config, "team.slug") == team_slug
            ] if get_nested(user, "mate_configs") else [],
            projects=[
                Project(
                    id=get_nested(project, "id"),
                    name=get_nested(project, "name"),
                    description=get_nested(project, "description")
                ) for project in get_nested(user, "projects")
            ] if get_nested(user, "projects") else [],

            email_encrypted=get_nested(user, "email"),
            password_encrypted=get_nested(user, "password"),
            api_token_encrypted=get_nested(user, "api_token"),
            other_settings_encrypted=get_nested(user, "other_settings"),
            likes_encrypted=get_nested(user, "likes"),
            dislikes_encrypted=get_nested(user, "dislikes"),
            goals_encrypted=get_nested(user, "goals"),
            recent_topics_encrypted=get_nested(user, "recent_topics")
        ) if user_access == "full_access" else User(
            id=user["id"],
            username=get_nested(user, "username")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get the user.")
        raise HTTPException(status_code=500, detail=f"Failed to get the user: {str(e)}")