from server.api.models.billing.billing_get_balance import BillingBalanceOutput
import logging
from server.api.endpoints.users.get_user import get_user

# Set up logger
logger = logging.getLogger(__name__)


async def get_balance(
        team_slug: str,
        api_token: str,
        for_team: bool
    ) -> BillingBalanceOutput:
    """
    Get the current balance of credits for a team or user.
    """
    logger.debug(f"Getting balance ...")

    # TODO: Implement this endpoint
    # check first if the user is allowed to use the team balance
    # if so, return the balance of the team from memory (or if not in memory, get it from the database and store it in memory)

    # if not, return the balance of the user from memory (or if not in memory, get it from the database and store it in memory)
    user = await get_user(
        api_token=api_token,
        fields=["balance_credits"]
    )
    balance_credits = user.balance_credits

    return BillingBalanceOutput(
        for_user=not for_team,
        for_team_slug=team_slug if for_team else None,
        balance_credits=balance_credits
    )