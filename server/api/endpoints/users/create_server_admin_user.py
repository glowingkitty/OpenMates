from typing import Optional
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.cms.cms import make_strapi_request
from server.api.models.users.users_create import UsersCreateOutput, UsersCreateInput
from server.api.models.users.users_create_new_api_token import UsersCreateNewApiTokenInput
from server.api.endpoints.users.create_new_api_token import create_new_api_token
from server.api.endpoints.teams.get_teams import get_teams
from server.api.models.teams.teams_get_all import TeamsGetAllOutput
import logging

logger = logging.getLogger(__name__)

async def create_server_admin_user(
        input: UsersCreateInput,
        team_name: str
) -> UsersCreateOutput:
    """
    Create a new user with server admin rights.
    """
    try:
        logger.debug("Creating a new OpenMates server admin user...")

        # Create new team
        status_code, json_response = await make_strapi_request(
            method='post',
            endpoint='teams',
            data={
                "data": {
                    "name": team_name,
                    "slug": team_name.lower().replace(" ", "-")
                }
            }
        )
        if status_code == 200:
            logger.debug("Successfully created the team for the server admin user")
        else:
            logger.error("Failed to create the team for the server admin user")
            raise HTTPException(status_code=500, detail="Failed to create the team")

        # Create a new API token
        create_new_api_token_output = await create_new_api_token(
            input=UsersCreateNewApiTokenInput(
                username=input.username,
                password=input.password
            )
        )
        api_token = create_new_api_token_output["api_token"]

        # Create the server admin user
        status_code, json_response = await make_strapi_request(
            method='post',
            endpoint='user-accounts',
            data={
                "data": {
                    "username": input.username,
                    "email": input.email,
                    "password": input.password,
                    "is_server_admin": True,
                    "api_token": api_token
                }
            }
        )

        if status_code == 200:
            logger.info("Successfully created the server admin user")
            logger.info(f"Save the API token under DEFAULT_ADMIN_API_TOKEN in .env: {api_token}")
            return UsersCreateOutput(
                id=json_response["data"]["id"],
                name=json_response["data"]["name"],
                username=json_response["data"]["username"],
                email=json_response["data"]["email"],
                api_token=json_response["data"]["api_token"]
            )
        else:
            logger.error("Failed to create the server admin user")
            raise HTTPException(status_code=500, detail="Failed to create the server admin user")

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to create the server admin user")
        raise HTTPException(status_code=500, detail="Failed to create the server admin user")
