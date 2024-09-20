import logging
from typing import List, Optional, Literal
from fastapi import HTTPException
from server.cms.endpoints.users.get_user import get_user as get_user_from_cms
from server.memory.memory import get_user_from_memory, save_user_to_memory
from server.api.models.users.users_get_one import User, UserEncrypted
from server.api.errors.errors import UserNotFoundError, InvalidAPITokenError, InvalidPasswordError
from server.api.security.crypto import decrypt, verify_hash
import json

# Set up logger
logger = logging.getLogger(__name__)


async def get_user(
        team_slug: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_token: Optional[str] = None,
        user_access: str = "full_access",
        fields: Optional[List[str]] = None
    ) -> User:
    """
    Get a specific user.
    """
    try:
        logger.debug("Getting a specific user ...")

        # Split the fields by comma if provided as a single string
        if fields:
            for field in fields:
                # if there is a comma in the field, split it and remove spaces
                if "," in field:
                    fields.remove(field)
                    fields.extend(field.split(","))
                elif ";" in field:
                    fields.remove(field)
                    fields.extend(field.split(";"))
                elif " " in field:
                    fields.remove(field)
                    fields.extend(field.split(" "))
            # remove duplicates and spaces
            fields = [field.strip() for field in fields]
            fields = list(set(fields))
            logger.debug(f"Fields: {fields}")
        else:
            fields = User.api_output_fields

        # TODO also implement same save / load from memory logic for getting all users

        # TODO also implement same save / load from memory logic for teams

        if not api_token and not (username and password):
            raise ValueError("You need to provide either an api token or username and password.")

        # separate uid (first 32 characters) from api token (following 32 characters)
        user_id: str = api_token[:32]

        # attempt to get user from memory
        user: UserEncrypted = get_user_from_memory(user_id=user_id, fields=fields)

        if user:
            logger.debug(f"User object found in memory: {user}")
            # check if all required fields are in the user object and have non-None values, if not, get user from cms
            for field in fields:
                logger.debug(f"Proccesing field: {field}")
                if not hasattr(user, field) or getattr(user, field) is None:
                    logger.debug(f"User object does not have field '{field}' or it's None. Setting user to None to get it from cms.")
                    user = None
                    break

        # if user is not found in memory, get it from cms
        if user is None:
            user: UserEncrypted = await get_user_from_cms(user_id=user_id,user_access=user_access, team_slug=team_slug, fields=fields)

            if user:
                # if user found, save it to memory
                save_user_to_memory(user_id=user_id, user_data=user)


        # if user is not found in cms, raise error
        if user is None:
            raise UserNotFoundError()

        # verify api token
        if api_token and not verify_hash(hashed_text=user.api_token, text=api_token[32:]):
            raise InvalidAPITokenError(log_message="The user token is invalid.")

        # verify password
        if password and not verify_hash(hashed_text=user.password, text=password):
            raise InvalidPasswordError(log_message="The user password is invalid.")

        # verify username
        if username and not user.username == username:
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

        output_user = User(**user_fields)

        logger.debug(f"Successfully loaded user.")

        return output_user

    except HTTPException:
        raise

    except Exception:
        logger.exception("Unexpected error during get user")
        raise HTTPException(status_code=500, detail="Unexpected error during get user")