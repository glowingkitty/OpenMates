import os
import httpx
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

async def validate_invite_code(
    invite_code: str
) -> None:
    """
    Check if an invite code is valid by looking it up in the Directus database.
    """
    try:
        # Use the default Directus port since we're in the same compose network
        directus_url = "http://cms:8055"  # Fixed port since this is Directus's default
        admin_token = os.getenv("DIRECTUS_ADMIN_TOKEN")

        if not admin_token:
            logger.error("Directus admin token missing")
            raise HTTPException(
                status_code=500,
                detail="Server configuration error"
            )

        logger.debug(f"Connecting to Directus at {directus_url}")

        # Query Directus for the invite code
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{directus_url}/items/invitecode",
                headers={"Authorization": f"Bearer {admin_token}"},
                params={
                    "filter[code][_eq]": invite_code
                }
            )

            if response.status_code != 200:
                logger.error(f"Directus API error: {response.status_code}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking invite code"
                )

            data = response.json()
            if len(data.get("data", [])) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid invite code"
                )

    except Exception as e:
        logger.error(f"Error validating invite code: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error checking invite code"
        )
