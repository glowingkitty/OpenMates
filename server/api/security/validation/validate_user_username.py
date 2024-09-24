from fastapi import HTTPException
from server.cms.cms import make_strapi_request
import logging

# Set up logger
logger = logging.getLogger(__name__)


async def validate_user_username(username:str) -> bool:
    """
    Validate if the user username is already taken
    """
    try:
        logger.debug("Validating if the user username is already taken ...")

        # try to get the user from strapi
        fields = [
            "username"
        ]
        filters = [
            {
                "field": "username",
                "operator": "$eq",
                "value": username
            }
        ]
        status_code, user_json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=fields,
            filters=filters
        )

        # check if the username is already taken
        if status_code == 200 and user_json_response:
            logger.debug("The username is already taken.")
            raise HTTPException(status_code=400, detail="The username is not available. Please choose another one.")
        else:
            logger.debug("The username is not taken.")
            return True

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to validate the username.")
        raise HTTPException(status_code=500, detail="Failed to validate the username.")