################
# Default Imports
################
import sys
import os
import re
import uuid

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from server.api.endpoints.users.get_user import get_user

async def check_user_balance(
        team_slug: str,
        api_token: str,
        required_credits: int
    ) -> bool:
    """
    Check if a user has enough balance to perform an action.
    """
    user_data = await get_user(
        team_slug=team_slug,
        request_sender_api_token=api_token,
        api_token=api_token,
        output_raw_data=True,
        output_format="dict"
    )

    user_balance = user_data.get("balance", 0)

    if user_balance >= required_credits:
        return True
    else:
        return False