from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional
import pycountry

# Generate a set of valid currency codes
VALID_CURRENCIES = {currency.alpha_3 for currency in pycountry.currencies}

class BankAccountInfo(BaseModel):
    account_name: str = Field(..., description="The name of the bank account")
    account_number: str = Field(..., description="The account number")
    currency_code: str = Field(..., description="The currency code for the account")
    opening_balance: int = Field(default=0, description="The opening balance of the account")
    bank_name: Optional[str] = Field(None, description="The name of the bank")
    bank_address: Optional[str] = Field(None, description="The address of the bank")
    bank_phone: Optional[str] = Field(None, description="The phone number of the bank")
    enabled: int = Field(default=1, description="Whether the account is enabled or not")

    model_config = ConfigDict(extra="forbid")

    @field_validator('currency_code')
    @classmethod
    def validate_currency_code(cls, v):
        if v.upper() not in VALID_CURRENCIES:
            raise ValueError(f"Invalid currency code: {v}")
        return v.upper()

    @field_validator('account_number')
    @classmethod
    def validate_account_number(cls, v):
        if not v.strip():
            raise ValueError("Account number cannot be empty")
        return v

    @field_validator('opening_balance')
    @classmethod
    def validate_opening_balance(cls, v):
        if v < 0:
            raise ValueError("Opening balance cannot be negative")
        return v

class AkauntingBankAccountOutput(BankAccountInfo):
    id: int = Field(..., description="The ID of the bank account in Akaunting")