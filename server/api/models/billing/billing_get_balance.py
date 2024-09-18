################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from pydantic import BaseModel, Field, model_validator
from typing import Optional

# GET /billing/get_balance (get the balance of the user)

max_overdraft = 50

class BillingGetBalanceInput(BaseModel):
    for_team: bool = Field(..., description="If true, the balance is retrieved for the current selected team (assuming you are allowed to use the team balance), otherwise for your user")

class BillingGetBalanceOutput(BaseModel):
    for_user: bool = Field(..., description="If true, the balance is retrieved for the current user, otherwise for the current team")
    for_team_slug: Optional[str] = Field(None, description="Slug of the team, for which the balance was successfully retrieved. If you set 'for_team' to true and this value is None, it means you are not allowed to access the team balance.")
    balance_credits: int = Field(..., description="Balance of the team or user in credits")

    @model_validator(mode='after')
    def validate_for_user_or_for_team(self):
        if self.for_user == True and self.for_team_slug is not None:
            raise ValueError("You can only request either the balance of the user or the balance of the team, not both")
        return self

    @model_validator(mode='after')
    def validate_balance_credits(self):
        if self.balance_credits < -max_overdraft:
            raise ValueError(f"Balance credits cannot be less than {-max_overdraft} credits")
        return self

billing_get_balance_input_example = {
    "for_team": True
}

billing_get_balance_output_example = {
    "for_user": False,
    "for_team_slug": "openmates_devs",
    "balance_credits": 429290
}