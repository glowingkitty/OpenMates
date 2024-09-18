################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from server.api.models.billing.billing_get_balance import BillingBalanceOutput
from typing import Literal


async def update_balance(
        team_slug: str,
        api_token: str,
        for_team: bool,
        amount: int,
        action: Literal["add", "subtract"] = "subtract"
    ) -> BillingBalanceOutput:
    """
    Update the balance of credits for a team or user.
    """
    # Ensure amount is always positive
    amount = abs(amount)

    # TODO: Implement this endpoint
    # check first if the user is allowed to use the team balance
    # if so, update the balance of the team both in memory and in the database

    # if not, update the balance of the user both in memory and in the database

    return BillingBalanceOutput(
        for_user=not for_team,
        for_team_slug=team_slug if for_team else None,
        balance_credits=0
    )