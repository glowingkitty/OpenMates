from typing import Literal
from server.api.endpoints.users.get_user import get_user
from server.api.models.users.users_get_one import User
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


async def validate_user_data_access(
        team_slug: str,
        request_team_slug: str,
        token: str = None,
        username: str = None,
        password: str = None,
        request_endpoint: Literal["get_one_user", "get_all_users"] = "get_one_user"
    ) -> str:
    """
    Validate if the user has access to the user data
    """
    try:
        logger.debug("Validating if the user has access to the user data ...")

        user: User = await get_user(
            team_slug=team_slug,
            username=username,
            api_token=token,
            fields=["is_server_admin","username","teams"]
        )

        if request_endpoint == "get_one_user":
            if username and user.username == username:
                logger.debug("User is trying to access its own data.")
                return "full_access"
            if user.is_server_admin:
                logger.debug("User is a server admin and has the permission to access all basic user data.")
                return "basic_access"
            if request_team_slug:
                for team in user.teams:
                    if team.slug == request_team_slug and team.admin == True:
                        logger.debug("User is a team admin and has the permission to access all basic user data on the team.")
                        return "basic_access"
            logger.debug("User does not have the permission to access the user data.")
            raise HTTPException(status_code=404, detail="User not found. Either the username is wrong, the team slug is wrong or the user is not part of the team or you don't have the permission to access this user.")
        elif request_endpoint == "get_all_users":
            if user.is_server_admin:
                logger.debug("User is a server admin and has the permission to access all basic user data.")
                return "basic_access_for_all_users_on_server"
            if request_team_slug:
                for team in user.teams:
                    if team.slug == request_team_slug and team.admin == True:
                        logger.debug("User is a team admin and has the permission to access all basic user data on the team.")
                        return "basic_access_for_all_users_on_team"
            logger.debug("User is only allowed to access its own data.")
            return "basic_access_for_own_user_only"

    except Exception:
        logger.exception("Failed to validate the user data access.")