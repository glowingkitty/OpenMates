import logging
from server.api.security.crypto import verify_hash
from server.api.errors.errors import InvalidAPITokenError, UserNotFoundError
from server.api.endpoints.users.get_user import get_user
from server.api.models.users.users_get_one import User

# Set up logger
logger = logging.getLogger(__name__)


async def validate_api_token(
    token: str,
    team_slug: str = None
    ) -> str:
    """
    Verify if the API token is valid for the requested team
    """
    try:
        logger.debug("Verifying User API token...")
        # get the user data via get_user (which will first check in memory, then in cms)
        try:
            # get_user will also verify the api token
            user: User = await get_user(
                api_token=token,
                fields=["is_server_admin", "teams"]
            )
        except UserNotFoundError:
            raise InvalidAPITokenError(log_message="The user does not exist.")

        # verify that the user is a server admin
        if user.is_server_admin:
            logger.debug("The user is a server admin.")
            return "user_is_server_admin"

        # verify that the user is a member of the team
        if team_slug and user.teams and (team_slug in [team.slug for team in user.teams]):
            logger.debug("The user is a member of the team.")
            return "user_is_member_of_team"

        # some endpoints don't require a team slug
        if not team_slug:
            logger.debug("No team slug provided. Can't validate if user is a member of the team.")
            return "no_team_slug_provided"

        # if the user is not a member of the team, raise an error
        raise InvalidAPITokenError(log_message="The user is not a member of the team.")


    except InvalidAPITokenError:
        raise
    except Exception:
        raise InvalidAPITokenError()