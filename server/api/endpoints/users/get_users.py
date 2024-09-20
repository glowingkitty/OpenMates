import logging
from server.api.models.users.users_get_all import UsersGetAllOutput
from fastapi import HTTPException
from server.cms.endpoints.users.get_users import get_users as get_many_users_from_cms
from server.memory.memory import get_many_users_from_memory, save_many_users_to_memory

# Set up logger
logger = logging.getLogger(__name__)


async def get_users(
        user_access: str,
        team_slug: str,
        page: int = 1,
        pageSize: int = 25
    ) -> UsersGetAllOutput:
    """
    Get a list of all users on a team
    """
    try:
        logger.debug("Getting a list of all users on a team ...")

        if user_access != "basic_access_for_all_users_on_team" and user_access != "basic_access_for_all_users_on_server":
            raise HTTPException(status_code=403, detail="You are not authorized to access this endpoint")

        # attempt to get users from memory
        users: UsersGetAllOutput = get_many_users_from_memory(team_slug=team_slug, page=page, pageSize=pageSize)

        if not users:
            users = await get_many_users_from_cms(team_slug=team_slug, page=page, pageSize=pageSize)

            # save users to memory
            save_many_users_to_memory(team_slug=team_slug, users=users)

        return users

    except HTTPException:
        raise

    except Exception:
        logger.exception("Unexpected error during get users")
        raise HTTPException(status_code=500, detail="Unexpected error during get users")
