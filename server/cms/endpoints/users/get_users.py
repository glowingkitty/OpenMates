from server.cms.cms import make_strapi_request, get_nested
from server.api.models.users.users_get_all import UsersGetAllOutput
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


async def get_users(
        team_slug: str,
        page: int = 1,
        pageSize: int = 25
    ) -> UsersGetAllOutput:
    """
    Get a list of all users on a team
    """
    try:
        logger.debug("Getting a list of all users on a team from CMS ...")

        fields = [
            "username",
            "id"
        ]
        filters = [
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_slug
            }
        ]

        # Get the users with pagination info
        status_code, json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=fields,
            filters=filters,
            page=page,
            pageSize=pageSize
        )

        if status_code == 200:
            users = [
                {
                    "id": get_nested(user, "id"),
                    "username": get_nested(user, "username")
                }
                for user in json_response.get("data", [])
            ]

            # Extract pagination info from the response
            pagination = json_response.get("meta", {}).get("pagination", {})
            total = pagination.get("total", 0)
            page_count = pagination.get("pageCount", 0)

            meta = {
                "pagination": {
                    "page": page,
                    "pageSize": pageSize,
                    "pageCount": page_count,
                    "total": total
                }
            }
            users_get_all_output = {
                "data": users,
                "meta": meta
            }
            logger.debug("Successfully got a list of all users on a team from CMS")
            return UsersGetAllOutput(**users_get_all_output)
        else:
            logger.exception("Failed to get a list of all users on a team from CMS")

    except HTTPException:
        raise

    except Exception:
        logger.exception("Unexpected error during get users")