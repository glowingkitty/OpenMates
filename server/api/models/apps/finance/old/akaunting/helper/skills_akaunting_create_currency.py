from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional
import pycountry

# Generate a set of valid currency codes
VALID_CURRENCIES = {currency.alpha_3 for currency in pycountry.currencies}

class CurrencyInfo(BaseModel):
    name: str = Field(..., description="The name of the currency")
    code: str = Field(..., description="The currency code")
    rate: float = Field(default=1, description="The exchange rate of the currency")
    precision: int = Field(default=2, description="The number of decimal places for the currency")
    symbol: str = Field(..., description="The symbol of the currency")
    symbol_first: int = Field(default=0, description="Whether the symbol appears before the amount")
    decimal_mark: str = Field(default=".", description="The decimal separator for the currency")
    thousands_separator: str = Field(default=",", description="The thousands separator for the currency")
    enabled: int = Field(default=1, description="Whether the currency is enabled or not")

    model_config = ConfigDict(extra="forbid")

    @field_validator('code')
    @classmethod
    def validate_currency_code(cls, v):
        if v.upper() not in VALID_CURRENCIES:
            raise ValueError(f"Invalid currency code: {v}")
        return v.upper()

    @field_validator('rate')
    @classmethod
    def validate_rate(cls, v):
        if v <= 0:
            raise ValueError("Rate must be greater than 0")
        return v

    @field_validator('precision')
    @classmethod
    def validate_precision(cls, v):
        if v < 0:
            raise ValueError("Precision cannot be negative")
        return v

class AkauntingCurrencyOutput(CurrencyInfo):
    id: int = Field(..., description="The ID of the currency in Akaunting")