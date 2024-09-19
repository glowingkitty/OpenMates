import logging
from typing import Optional
from fastapi import HTTPException
from server.api.errors.errors import InvalidAPITokenError
from server.api.security.validation.validate_api_token import validate_api_token
from server.api.security.validation.validate_user_data_access import validate_user_data_access
from server.api.security.validation.validate_file_access import validate_file_access

# Set up logger
logger = logging.getLogger(__name__)

# TODO add tests

async def validate_permissions(
    endpoint: str,
    user_api_token: str,
    team_slug: Optional[str] = None,
    user_username: Optional[str] = None,
    user_password: Optional[str] = None,
    user_api_token_already_checked: Optional[bool] = False,
    required_permissions: Optional[list] = None
) -> str:
    try:
        logger.debug(f"Validating permissions for endpoint '{endpoint}'...")

        # TODO handle different endpoint usecases

        # TODO if username and password instead of token are given, handle that

        # /uploads/...
        if endpoint.startswith("/uploads/"):
            access = await validate_file_access(
                user_api_token=user_api_token,
                filename=endpoint.split("/")[-1],
                team_slug=team_slug
            )


        # /users
        if endpoint == "/users":
            access = await validate_user_data_access(
                token=user_api_token,
                request_team_slug=team_slug,
                username=user_username,
                password=user_password,
                request_endpoint="get_all_users"
            )


        # else just check the token
        if not user_api_token_already_checked:
            access = await validate_api_token(
                token=user_api_token,
                team_slug=team_slug
            )

        logger.debug(f"Access: '{access}'")

        return access

        # TODO handle check for access to create, delete or update mate

    except InvalidAPITokenError:
        raise

    except Exception:
        logger.exception("Unexpected error during permission validation")
        raise HTTPException(status_code=500, detail="Unexpected error during permission validation")