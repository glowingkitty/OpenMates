from server.cms.cms import make_strapi_request
import logging

# Set up logger
logger = logging.getLogger(__name__)

async def check_for_admin_user() -> bool:
    """
    Make request to strapi to check if any user with server admin rights exists.
    Keep in mind: admin in this case means admin in the OpenMates user model sense
    (user-account.is_server_admin is True), NOT admin in the Strapi user model sense.

    Returns:
        bool: True if at least one admin user exists, False otherwise
    """
    try:
        # We only need minimal fields to check for admin status
        fields = ["is_server_admin"]

        # Filter for users where is_server_admin is true
        filters = [
            {"field": "is_server_admin", "operator": "$eq", "value": True}
        ]

        logger.debug("Checking for existence of OpenMates server admin users in Strapi")
        status_code, json_response = await make_strapi_request(
            method="get",
            endpoint="user-accounts",
            filters=filters,
            fields=fields
        )

        # Check if we got a successful response and if there are any results
        if status_code == 200 and json_response["data"]:
            logger.info("Found at least one OpenMates server admin user")
            return True

        logger.info("No OpenMates server admin users found")
        return False

    except Exception as e:
        logger.exception("Error while checking for OpenMates server admin users")
        return False
