from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional
from datetime import datetime


class BankTransactionInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the bank transaction")
    datetime: str = Field(..., description="The date, time, and timezone of the bank transaction (ISO 8601 format: YYYY-MM-DDTHH:MM:SS±HH:MM)")
    value: float = Field(..., description="The value of the bank transaction (can be positive or negative)")
    account: str = Field(..., description="The bank account for the transaction")
    currency_rate: Optional[float] = Field(None, description="The currency rate for the transaction")
    payment_method: str = Field("bank transfer", description="The payment method ('bank transfer' or 'cash')")
    description: Optional[str] = Field(None, description="Description of the transaction")
    number: Optional[str] = Field(None, description="The transaction number (auto-generated)")
    reference: Optional[str] = Field(None, description="Reference for the transaction")

    model_config = ConfigDict(extra="forbid")

    @field_validator('datetime')
    @classmethod
    def validate_datetime(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%dT%H:%M:%S%z')
        except ValueError:
            raise ValueError(f"Invalid datetime format. Use YYYY-MM-DDTHH:MM:SS±HH:MM: {v}")
        return v

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        if v <= 0:
            raise ValueError(f"Value must be greater than 0: {v}")
        return v

    @field_validator('payment_method')
    @classmethod
    def validate_payment_method(cls, v):
        if v not in ['bank transfer', 'cash']:
            raise ValueError(f"Payment method must be 'bank transfer' or 'cash': {v}")
        return v

    @field_validator('currency_rate')
    @classmethod
    def validate_currency_rate(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Currency rate must be positive: {v}")
        return v