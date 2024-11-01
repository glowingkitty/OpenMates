from typing import List, Optional, Union, Dict, Literal
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.models.users.users_create_new_api_token import UsersCreateNewApiTokenInput, UsersCreateNewApiTokenOutput
from server.api.endpoints.users.get_user import get_user
from server.api.security.validation.validate_api_token import validate_api_token
from server.api.models.users.users_get_one import UserGetOneOutput, UserGetOneInput
import secrets
import logging

# Set up logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def create_new_api_token(
        input: UsersCreateNewApiTokenInput
    ) -> UsersCreateNewApiTokenOutput:
    """
    Create a new API token for the user
    """
    logger.debug("Creating a new API token ...")
    # create a new uid
    uid = secrets.token_hex(16)

    # create a new API token
    api_token = secrets.token_hex(16)

    # make sure the new uid and API token don't already exist
    try:
        while await validate_api_token(token=uid+api_token):
            uid = secrets.token_hex(16)
            api_token = secrets.token_hex(16)
    except HTTPException as e:
        if e.status_code == 403 or e.status_code == 404 or e.status_code == 401:
            logger.debug("The token does not exist yet. Continuing ...")
        else:
            raise e

    # try to find the user in the database, if it already exists, replace the existing API token
    # else, only create a new API token (but don't update any user data)
    if input.username and input.password:
        logger.debug(f"Trying to find user with username: {input.username} and password: {input.password}")
        user: UserGetOneOutput = await get_user(
            input=UserGetOneInput(
                username=input.username,
                password=input.password
            )
        )

        if user and "id" in user:
            logger.debug("User found. Replacing the existing uid and api_token ...")
            # TODO create update_user function
            update_user(id=user["id"], uid=uid, api_token=api_token)

        else:
            raise HTTPException(status_code=404, detail="Could not find the requested user.")

    logger.debug(f"Successfully created a new API token.")
    return {
        "api_token": uid+api_token
    }