from typing import Optional
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.cms.cms import make_strapi_request
from server.api.models.users.users_create import UsersCreateOutput, UsersCreateInput
from server.api.models.users.users_create_new_api_token import UsersCreateNewApiTokenInput
from server.api.endpoints.users.create_new_api_token import create_new_api_token
from server.api.endpoints.teams.get_teams import get_teams
from server.api.models.teams.teams_get_all import TeamsGetAllOutput
from server.api.models.teams.teams_get_one import Team
import logging
from server.api.security.crypto import hashing
logger = logging.getLogger(__name__)

async def create_server_admin_user(
        input: UsersCreateInput,
        team_name: str
) -> UsersCreateOutput:
    """
    Create a new user with server admin rights.
    Handles cases where team or user might already exist.
    Encrypts password and API token using Argon2.
    """
    try:
        logger.debug("Creating a new OpenMates server admin user...")

        # Check if team already exists
        team_slug = team_name.lower().replace(" ", "-")
        status_code, existing_teams = await make_strapi_request(
            method='get',
            endpoint='teams',
            filters=[{'field': 'slug', 'operator': 'eq', 'value': team_slug}]
        )

        # Get or create team
        if not existing_teams.get('data'):
            logger.debug(f"Creating a new team with name: {team_name}")
            status_code, team_response = await make_strapi_request(
                method='post',
                endpoint='teams',
                data={
                    "data": {
                        "name": team_name,
                        "slug": team_slug
                    }
                }
            )
            team_id = team_response.get('data', {}).get('id')
        else:
            logger.debug(f"Team '{team_name}' already exists, using existing team")
            team_id = existing_teams['data'][0]['id']

        if not team_id:
            logger.error("Failed to get or create team")
            raise HTTPException(status_code=500, detail="Failed to get or create team")

        # Check if user already exists
        status_code, existing_users = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            filters=[{'field': 'email', 'operator': 'eq', 'value': input.email}]
        )

        if existing_users.get('data'):
            logger.info(f"User with email {input.email} already exists")
            user_data = existing_users['data'][0]
            return UsersCreateOutput(
                id=user_data['id'],
                name=user_data.get('name', ''),
                username=user_data['username'],
                email=user_data['email'],
                api_token=user_data.get('api_token', ''),
                teams=user_data.get('teams', [])
            )

        # Create a new API token and hash it
        create_new_api_token_output = await create_new_api_token(
            input=UsersCreateNewApiTokenInput()
        )
        raw_api_token = create_new_api_token_output["api_token"]
        hashed_api_token = hashing(raw_api_token)

        # Hash the password
        hashed_password = hashing(input.password)

        # TODO fix fundamental hashing and verifying logic

        # set the user UID based on the api token
        user_uid = raw_api_token[:32]

        # Create the server admin user
        status_code, json_response = await make_strapi_request(
            method='post',
            endpoint='user-accounts',
            data={
                "data": {
                    "username": input.username,
                    "email": input.email,
                    "password": hashed_password,  # Use hashed password
                    "is_server_admin": True,
                    "api_token": hashed_api_token,  # Use hashed API token
                    "uid": user_uid,  # Add UID
                    "teams": [team_id],
                    "teams_where_user_is_admin": [team_id]
                }
            }
        )

        if status_code == 200:
            logger.info("Successfully created the server admin user and added to team")
            logger.info(f"Save the API token under DEFAULT_ADMIN_API_TOKEN in .env: {raw_api_token}")  # Log the raw token
            return UsersCreateOutput(
                id=json_response["data"]["id"],
                name=input.name,
                username=input.username,
                email=input.email,
                api_token=raw_api_token,  # Return the raw token to the client
                teams=[Team(
                    id=team_id,
                    name=team_name,
                    slug=team_slug
                )]
            )
        else:
            logger.error("Failed to create the server admin user")
            raise HTTPException(status_code=500, detail="Failed to create the server admin user")

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to create the server admin user")
        raise HTTPException(status_code=500, detail="Failed to create the server admin user")
