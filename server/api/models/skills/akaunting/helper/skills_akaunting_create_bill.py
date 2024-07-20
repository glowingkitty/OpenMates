from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional, List
import pycountry
from datetime import datetime

# Generate sets of valid currency and country codes
VALID_CURRENCIES = {currency.alpha_3 for currency in pycountry.currencies}
VALID_COUNTRIES = {country.alpha_2 for country in pycountry.countries}

# Define valid expense categories
VALID_EXPENSE_CATEGORIES = {'Purchase', 'Refund', 'Other'}


class TaxInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the tax")
    name: str = Field(..., description="The name of the tax")
    rate: float = Field(..., description="The rate of the tax")

    @field_validator('rate')
    @classmethod
    def validate_rate(cls, v):
        if v < 0 or v > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {v}")
        return v


class ItemInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the item")
    name: str = Field(..., description="The name of the item")
    description: Optional[str] = Field(None, description="The description of the item")
    quantity: int = Field(..., description="The quantity of the item")
    net_price: float = Field(..., description="The net price of the item (before taxes)")
    tax: Optional[TaxInfo] = Field(None, description="The tax information for the item")

    @field_validator('quantity')
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError(f"Quantity must be greater than 0: {v}")
        return v

    @field_validator('net_price')
    @classmethod
    def validate_net_price(cls, v):
        if v < 0:
            raise ValueError(f"Net price cannot be negative: {v}")
        return v


class DiscountInfo(BaseModel):
    type: str = Field(..., description="The type of discount (percent or amount)")
    value: float = Field(..., description="The value of the discount")

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if v not in ['percent', 'amount']:
            raise ValueError(f"Discount type must be 'percent' or 'amount': {v}")
        return v

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        if v < 0:
            raise ValueError(f"Discount value cannot be negative: {v}")
        return v


class CategoryInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the category")
    name: Optional[str] = Field(None, description="The name of the category")

    @model_validator(mode='after')
    def check_id_or_name(self):
        if self.id is None and self.name is None:
            raise ValueError("Either 'id' or 'name' must be provided for the category")
        if self.name and self.name not in VALID_EXPENSE_CATEGORIES:
            raise ValueError(f"Invalid expense category. Must be one of: {', '.join(VALID_EXPENSE_CATEGORIES)}")
        return self


class SubCategoryInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the sub-category")
    name: Optional[str] = Field(None, description="The name of the sub-category")

    @model_validator(mode='after')
    def check_id_or_name(self):
        if self.id is None and self.name is None:
            raise ValueError("Either 'id' or 'name' must be provided for the sub-category")
        return self


class BankAccountInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the bank account")
    name: Optional[str] = Field(None, description="The name of the bank account")
    account_number: Optional[str] = Field(None, description="The account number of the bank account")

    @model_validator(mode='after')
    def check_id_or_name_or_account_number(self):
        if self.id is None and self.name is None and self.account_number is None:
            raise ValueError("Either 'id', 'name', or 'account_number' must be provided for the bank account")
        return self


class BillInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the bill")
    date: str = Field(..., description="The date of the bill (ISO 8601 format: YYYY-MM-DD)")
    due_date: str = Field(..., description="The due date of the bill (ISO 8601 format: YYYY-MM-DD)")
    order_number: Optional[str] = Field(None, description="The order number, if any")
    items: List[ItemInfo] = Field(..., description="List of items in the bill")
    discount: Optional[DiscountInfo] = Field(None, description="Discount information, if any")
    currency: str = Field(..., description="The currency of the bill")
    currency_convert_rate_to_default_currency: Optional[float] = Field(None, description="Conversion rate to default currency, if different")
    notes: Optional[str] = Field(None, description="Additional notes for the bill")
    category: CategoryInfo = Field(..., description="The main category of the expense")
    sub_category: Optional[SubCategoryInfo] = Field(None, description="Custom sub-category for the expense")
    attachment: Optional[List[str]] = Field(None, description="List of attachment file paths or URLs")
    bank_account: BankAccountInfo = Field(..., description="The bank account information for the bill")
    status: str = Field(default="draft", description="The status of the bill")

    model_config = ConfigDict(extra="forbid")

    @field_validator('date', 'due_date')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {v}")
        return v

    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v):
        if v.upper() not in VALID_CURRENCIES:
            raise ValueError(f"Invalid currency code: {v}")
        return v.upper()

    @field_validator('currency_convert_rate_to_default_currency')
    @classmethod
    def validate_currency_convert_rate(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Currency conversion rate must be positive: {v}")
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = ["draft", "received", "partial", "paid", "cancelled"]
        if v.lower() not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        return v.lower()


class AkauntingCreateBillOutput(BillInfo):
    id: int = Field(..., description="The ID of the created bill")