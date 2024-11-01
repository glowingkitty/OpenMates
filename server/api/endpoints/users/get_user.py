import logging
from typing import List, Optional, Literal
from fastapi import HTTPException
from server.cms.endpoints.users.get_user import get_user as get_user_from_cms
from server.memory.memory import get_user_from_memory, save_user_to_memory
from server.api.models.users.users_get_one import UserGetOneOutput, UserGetOneOutputEncrypted, UserGetOneInput
from server.api.errors.errors import UserNotFoundError, InvalidAPITokenError, InvalidPasswordError
from server.api.security.crypto import decrypt, verify_hash
import json

# Set up logger
logger = logging.getLogger(__name__)


async def get_user(
        input: UserGetOneInput
    ) -> UserGetOneOutput:
    """
    Get a specific user.
    """
    try:
        logger.debug("Getting a specific user ...")

        # TODO currently user can only find himself and get full user info
        # TODO enable team admin to get basic user info about all team members (id, username)
        # TODO enable server admin to get basic user info about all users (id, username)

        # TODO also implement same save / load from memory logic for teams

        # Split the fields by comma if provided as a single string
        if input.fields:
            for field in input.fields:
                # if there is a comma in the field, split it and remove spaces
                if "," in field:
                    input.fields.remove(field)
                    input.fields.extend(field.split(","))
                elif ";" in field:
                    input.fields.remove(field)
                    fields.extend(field.split(";"))
                elif " " in field:
                    input.fields.remove(field)
                    input.fields.extend(field.split(" "))
            # remove duplicates and spaces
            input.fields = [field.strip() for field in input.fields]
            input.fields = list(set(input.fields))
            logger.debug(f"Fields: {input.fields}")
        else:
            fields = UserGetOneOutput.api_output_fields

        if not input.api_token and not (input.username and input.password):
            raise ValueError("You need to provide either an api token or username and password.")

        # separate uid (first 32 characters) from api token (following 32 characters)
        user_id: str = input.api_token[:32]

        # attempt to get user from memory
        user: UserGetOneOutputEncrypted = get_user_from_memory(user_id=user_id, fields=input.fields)

        if user:
            # check if all required fields are in the user object and have non-None values, if not, get user from cms
            for field in input.fields:
                logger.debug(f"Proccesing field: {field}")
                if not hasattr(user, field) or getattr(user, field) is None:
                    logger.debug(f"User object does not have field '{field}' or it's None. Setting user to None to get it from cms.")
                    user = None
                    break

        # if user is not found in memory, get it from cms
        if user is None:
            user: UserGetOneOutputEncrypted = await get_user_from_cms(input=input)

            if user:
                # if user found, save it to memory
                save_user_to_memory(user_id=user_id, user_data=user)


        # if user is not found in cms, raise error
        if user is None:
            raise UserNotFoundError()

        # verify api token
        if input.api_token and not verify_hash(hashed_text=user.api_token, text=input.api_token[32:]):
            raise InvalidAPITokenError(log_message="The user token is invalid.")

        # verify password
        if input.password and not verify_hash(hashed_text=user.password, text=input.password):
            raise InvalidPasswordError(log_message="The user password is invalid.")

        # verify username
        if input.username and not user.username == input.username:
            raise UserNotFoundError()

        # Make sure user is a member of the team
        if input.team_slug and user.teams and (input.team_slug not in [team.slug for team in user.teams]):
            raise UserNotFoundError()

        # decrypt user data and fill non-encrypted fields
        user_fields = {
            "id": user_id,
            "username": user.username,
            "is_server_admin": user.is_server_admin,
            "email": decrypt(user.email),
            "teams": user.teams,
            "profile_image": user.profile_image,
            "balance_credits": user.balance_credits,
            "mates_default_privacy_settings": user.mates_default_privacy_settings,
            "mate_configs": user.mate_configs,
            "other_settings": json.loads(decrypt(user.other_settings)) if user.other_settings else None,
            "projects": user.projects,
            "likes": json.loads(decrypt(user.likes)) if user.likes else None,
            "dislikes": json.loads(decrypt(user.dislikes)) if user.dislikes else None,
            "topics_outside_my_bubble_that_i_should_consider": user.topics_outside_my_bubble_that_i_should_consider,
            "goals": json.loads(decrypt(user.goals)) if user.goals else None,
            "recent_topics": json.loads(decrypt(user.recent_topics)) if user.recent_topics else None
        }

        # Remove None values
        user_fields = {k: v for k, v in user_fields.items() if v is not None}

        output_user = UserGetOneOutput(**user_fields)

        logger.debug(f"Successfully loaded user.")

        return output_user

    except HTTPException:
        raise

    except Exception:
        logger.exception("Unexpected error during get user")
        raise HTTPException(status_code=500, detail="Unexpected error during get user")