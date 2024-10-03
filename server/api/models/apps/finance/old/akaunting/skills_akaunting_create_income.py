

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import List, Optional
import re
from datetime import datetime
from server.api.models.apps.akaunting.helper.skills_akaunting_create_item import ItemInfo
from server.api.models.apps.akaunting.helper.skills_akaunting_create_bill import DiscountInfo

# Define a set of valid currency codes (you can expand this list as needed)
VALID_CURRENCIES = {'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR'}

# Define valid income categories
VALID_INCOME_CATEGORIES = {'Sales', 'Refund', 'Other'}

class CustomerInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the customer")
    name: Optional[str] = Field(None, description="The name of the customer")
    email: Optional[str] = Field(None, description="The email of the customer")
    phone: Optional[str] = Field(None, description="The phone number of the customer")
    tax_number: Optional[str] = Field(None, description="The tax number of the customer")
    currency: Optional[str] = Field(None, description="The currency used by the customer")
    address: Optional[str] = Field(None, description="The address of the customer")
    city: Optional[str] = Field(None, description="The city of the customer")
    zip_code: Optional[str] = Field(None, description="The ZIP code of the customer")
    state: Optional[str] = Field(None, description="The state of the customer")
    country: Optional[str] = Field(None, description="The country of the customer")
    website: Optional[str] = Field(None, description="The website of the customer")
    reference: Optional[str] = Field(None, description="The reference for the customer")

    @model_validator(mode='after')
    def check_id_or_name(self):
        if self.id is None and self.name is None:
            raise ValueError("Either 'id' or 'name' must be provided for the customer")
        return self

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v is not None:
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, v):
                raise ValueError(f"Invalid email format: {v}")
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is not None:
            pattern = r'^\+?[1-9]\d{1,14}$'
            if not re.match(pattern, v):
                raise ValueError(f"Invalid phone number format: {v}")
        return v

    @field_validator('website')
    @classmethod
    def validate_website(cls, v):
        if v is not None:
            pattern = r'^https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)$'
            if not re.match(pattern, v):
                raise ValueError(f"Invalid website URL format: {v}")
        return v

    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v):
        if v is not None:
            if v.upper() not in VALID_CURRENCIES:
                raise ValueError(f"Invalid currency code: {v}")
            return v.upper()
        return v


class CategoryInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the category")
    name: Optional[str] = Field(None, description="The name of the category")

    @model_validator(mode='after')
    def check_id_or_name(self):
        if self.id is None and self.name is None:
            raise ValueError("Either 'id' or 'name' must be provided for the category")
        if self.name and self.name not in VALID_INCOME_CATEGORIES:
            raise ValueError(f"Invalid income category. Must be one of: {', '.join(VALID_INCOME_CATEGORIES)}")
        return self


class SubCategoryInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the sub-category")
    name: Optional[str] = Field(None, description="The name of the sub-category")

    @model_validator(mode='after')
    def check_id_or_name(self):
        if self.id is None and self.name is None:
            raise ValueError("Either 'id' or 'name' must be provided for the sub-category")
        return self

class InvoiceInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the invoice")
    date: str = Field(..., description="The date of the invoice (ISO 8601 format: YYYY-MM-DD)")
    due_date: str = Field(..., description="The due date of the invoice (ISO 8601 format: YYYY-MM-DD)")
    invoice_number: Optional[str] = Field(None, description="The invoice number (auto-generated if not provided)")
    order_number: Optional[str] = Field(None, description="The order number, if any")
    items: List[ItemInfo] = Field(..., description="List of items in the invoice")
    tax_rate: Optional[float] = Field(None, description="The overall tax rate for the invoice")
    discount: Optional[DiscountInfo] = Field(None, description="Discount information, if any")
    currency: str = Field(..., description="The currency of the invoice")
    currency_convert_rate_to_default_currency: Optional[float] = Field(None, description="Conversion rate to default currency, if different")
    notes: Optional[str] = Field(None, description="Additional notes for the invoice")
    attachment: Optional[List[str]] = Field(None, description="List of attachment file paths or URLs")
    category: CategoryInfo = Field(..., description="The main category of the income")
    sub_category: Optional[SubCategoryInfo] = Field(None, description="Custom sub-category for the income")

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

    @field_validator('tax_rate')
    @classmethod
    def validate_tax_rate(cls, v):
        if v is not None:
            if v < 0 or v > 100:
                raise ValueError(f"Tax rate must be between 0 and 100: {v}")
        return v


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

class AkauntingCreateIncomeInput(BaseModel):
    customer: CustomerInfo = Field(..., description="Information about the customer (at least ID or name must be provided)")
    invoice: InvoiceInfo = Field(..., description="Information about the invoice")
    bank_transactions: Optional[List[BankTransactionInfo]] = Field(None, description="Information about the bank transaction(s), if any")

    model_config = ConfigDict(extra="forbid")

class AkauntingCreateIncomeOutput(BaseModel):
    id: int = Field(..., description="The ID of the created income")
    customer: CustomerInfo = Field(..., description="Customer information")
    invoice: InvoiceInfo = Field(..., description="Invoice information")
    bank_transactions: Optional[List[BankTransactionInfo]] = Field(None, description="Bank transaction information, if any")


akaunting_create_income_input_example = {
    "customer": {
        "name": "John Doe",
        "currency": "USD",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "invoice": {
        "date": "2023-06-01",
        "due_date": "2023-06-15",
        "items": [
            {
                "name": "Product A",
                "quantity": 1,
                "net_price": 100.00,
                "tax": {
                    "name": "VAT",
                    "rate": 20
                }
            }
        ],
        "currency": "USD",
        "category": {
            "name": "Sales"
        },
        "sub_category": {
            "name": "Online Sales"
        }
    }
}

akaunting_create_income_output_example = {
    "id": 1,
    "customer": {
        "id": 1,
        "name": "John Doe",
        "email": "john@example.com",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "invoice": {
        "id": 1,
        "date": "2023-06-01",
        "due_date": "2023-06-15",
        "invoice_number": "INV-001",
        "items": [
            {
                "id": 1,
                "name": "Product A",
                "price": 100.00,
                "quantity": 1,
                "tax": {
                    "id": 1,
                    "name": "VAT",
                    "rate": 20
                }
            }
        ],
        "currency": "USD",
        "category": {
            "id": 1,
            "name": "Sales"
        },
        "sub_category": {
            "id": 101,
            "name": "Online Sales"
        }
    },
    "bank_transactions": [
        {
            "id": 1,
            "datetime": "2023-06-01T10:15:00+00:00",
            "amount": 120.00,
            "account": "Main Checking Account",
            "payment_method": "bank transfer"
        }
    ]
}