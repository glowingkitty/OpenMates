import logging
from typing import List, Optional, Literal
from fastapi import HTTPException
from server.cms.endpoints.users.get_user import get_user as get_user_from_cms
from server.memory.memory import get_user_from_memory, save_user_to_memory
from server.api.models.users.users_get_one import User
from server.api.errors.errors import UserNotFoundError, InvalidAPITokenError, InvalidPasswordError
from server.api.security.crypto import decrypt, verify_hash
import json

# Set up logger
logger = logging.getLogger(__name__)


async def get_user(
        team_slug: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_token: Optional[str] = None,
        user_access: Optional[str] = None,
        use_cms_only: bool = False
    ) -> User:
    """
    Get a specific user.
    """
    try:
        logger.info("Getting a specific user ...")

        if not api_token and not (username and password):
            raise ValueError("You need to provide either an api token or username and password.")

        user = None

        # separate uid (first 32 characters) from api token (following 32 characters)
        user_id: str = api_token[:32]

        # attempt to get user from memory
        if not use_cms_only:
            user: User = get_user_from_memory(user_id=user_id)

            if user:
                logger.info("Loaded user from memory")

        # if user is not found in memory, get it from cms
        if user is None:
            user: User = await get_user_from_cms(user_id=user_id,user_access=user_access)

            if user:
                logger.info("Loaded user from cms")

                # if user found, save it to memory
                if not use_cms_only:
                    save_user_to_memory(user_id=user_id, user_data=user)
                    logger.info("Saved user to memory")


        # if user is not found in cms, raise error
        if user is None:
            raise UserNotFoundError()

        # verify api token
        if api_token and not verify_hash(hashed_text=user.api_token_encrypted, text=api_token[32:]):
            raise InvalidAPITokenError(log_message="The user token is invalid.")

        # verify password
        if password and not verify_hash(hashed_text=user.password_encrypted, text=password):
            raise InvalidPasswordError(log_message="The user password is invalid.")

        # decrypt user data and fill non-encrypted fields
        output_user = User(
            id=user_id,
            username=user.username,
            is_server_admin=user.is_server_admin,
            email=decrypt(user.email_encrypted) if user.email_encrypted else None,
            teams=user.teams,
            profile_picture_url=user.profile_picture_url,
            balance_credits=user.balance_credits,
            mates_default_privacy_settings=user.mates_default_privacy_settings,
            mates_custom_settings=user.mates_custom_settings,
            other_settings=json.loads(decrypt(user.other_settings_encrypted)) if user.other_settings_encrypted else None,
            projects=user.projects,
            likes=json.loads(decrypt(user.likes_encrypted)) if user.likes_encrypted else None,
            dislikes=json.loads(decrypt(user.dislikes_encrypted)) if user.dislikes_encrypted else None,
            topics_outside_my_bubble_that_i_should_consider=user.topics_outside_my_bubble_that_i_should_consider,
            goals=json.loads(decrypt(user.goals_encrypted)) if user.goals_encrypted else None,
            recent_topics=json.loads(decrypt(user.recent_topics_encrypted) if user.recent_topics_encrypted else None)
        )

        return output_user

    except HTTPException:
        raise

    except Exception:
        logger.exception("Unexpected error during get user")
        raise HTTPException(status_code=500, detail="Unexpected error during get user")