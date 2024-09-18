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

from server.api import *
################

from server.api.models.billing.billing_get_balance import BillingGetBalanceOutput

async def get_balance(
        team_slug: str,
        api_token: str,
        for_team: bool
    ) -> BillingGetBalanceOutput:
    """
    Get the current balance of credits for a team or user.
    """

    # TODO: Implement this endpoint
    # check first if the user is allowed to use the team balance
    # if so, return the balance of the team from memory (or if not in memory, get it from the database and store it in memory)

    # if not, return the balance of the user from memory (or if not in memory, get it from the database and store it in memory)

    return BillingGetBalanceOutput(
        for_user=not for_team,
        for_team_slug=team_slug if for_team else None,
        balance_credits=0
    )