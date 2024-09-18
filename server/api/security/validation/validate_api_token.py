import logging
from server.api.security.crypto import verify_hash
from server.api.errors.errors import InvalidAPITokenError
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
        logger.info("Verifying User API token...")
        # separate uid (first 32 characters) from api token (following 32 characters)
        uid: str = token[:32]
        api_token_from_request: str = token[32:]

        # get the user data via get_user (which will first check in memory, then in cms)
        user: User = await get_user(uid, cache=True)

        # if the user is not found, then the token is invalid
        if user is None:
            raise InvalidAPITokenError(log_message="The user does not exist.")

        # verify the api token
        if not verify_hash(user.api_token, api_token_from_request):
            raise InvalidAPITokenError(log_message="The user token is invalid.")

        # verify that the user is a server admin
        if user.is_server_admin:
            logger.info("The user is a server admin.")
            return "user_is_server_admin"

        # verify that the user is a member of the team
        if team_slug is not None and team_slug not in user.teams:
            raise InvalidAPITokenError(log_message="The user is not a member of the team.")

        # else the user is valid, because the user is a member of the team
        logger.info("The user is a member of the team.")
        return "user_is_member_of_team"

    except InvalidAPITokenError:
        raise
    except Exception:
        raise InvalidAPITokenError()