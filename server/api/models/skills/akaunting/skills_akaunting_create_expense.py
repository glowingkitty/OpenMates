from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import List, Optional
import re
from datetime import datetime, timezone

# Define a set of valid currency codes (you can expand this list as needed)
VALID_CURRENCIES = {'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR'}

# Define valid expense categories
VALID_EXPENSE_CATEGORIES = {'Purchase', 'Refund', 'Other'}

class VendorInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of the vendor")
    name: Optional[str] = Field(None, description="The name of the vendor")
    email: Optional[str] = Field(None, description="The email of the vendor")
    phone: Optional[str] = Field(None, description="The phone number of the vendor")
    tax_number: Optional[str] = Field(None, description="The tax number of the vendor")
    currency: Optional[str] = Field(None, description="The currency used by the vendor")
    address: Optional[str] = Field(None, description="The address of the vendor")
    city: Optional[str] = Field(None, description="The city of the vendor")
    zip_code: Optional[str] = Field(None, description="The ZIP code of the vendor")
    state: Optional[str] = Field(None, description="The state of the vendor")
    country: Optional[str] = Field(None, description="The country of the vendor")
    website: Optional[str] = Field(None, description="The website of the vendor")
    reference: Optional[str] = Field(None, description="The reference for the vendor")

    @model_validator(mode='after')
    def check_id_or_name(self):
        if self.id is None and self.name is None:
            raise ValueError("Either 'id' or 'name' must be provided for the vendor")
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

class AkauntingCreateExpenseInput(BaseModel):
    vendor: VendorInfo = Field(..., description="Information about the vendor (at least ID or name must be provided)")
    bill: Optional[BillInfo] = Field(None, description="Information about the bill, if available")
    bank_transaction: Optional[BankTransactionInfo] = Field(None, description="Information about the bank transaction, if available")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def check_bill_or_transaction(self):
        if self.bill is None and self.bank_transaction is None:
            raise ValueError("At least one of 'bill' or 'bank_transaction' must be provided")
        return self

class AkauntingCreateExpenseOutput(BaseModel):
    vendor: VendorInfo = Field(..., description="Vendor information")
    bill: Optional[BillInfo] = Field(None, description="Bill information, if provided")
    bank_transaction: Optional[BankTransactionInfo] = Field(None, description="Bank transaction information, if provided")

# Update the examples
akaunting_create_expense_input_example = {
    "vendor": {
        "name": "Acme Corp",
        "currency": "USD",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "bill": {
        "date": "2023-04-15",
        "due_date": "2023-05-15",
        "items": [
            {
                "name": "Widget",
                "quantity": 1,
                "net_price": 10.00,
                "tax": {
                    "name": "Sales Tax",
                    "rate": 20
                }
            }
        ],
        "currency": "USD",
        "category": {
            "name": "Purchase"
        },
        "sub_category": {
            "name": "Raw Materials"
        }
    },
    "bank_transaction": {
        "datetime": "2023-04-15T14:30:00+00:00",
        "value": 12.00,
        "account": "Main Checking Account",
        "payment_method": "bank transfer"
    }
}

akaunting_create_expense_output_example = {
    "vendor": {
        "id": 101,
        "name": "Acme Corp",
        "currency": "USD",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "bill": {
        "id": 201,
        "date": "2023-04-15",
        "due_date": "2023-05-15",
        "items": [
            {
                "id": 301,
                "name": "Widget",
                "quantity": 1,
                "net_price": 10.00,
                "tax": {
                    "id": 401,
                    "name": "Sales Tax",
                    "rate": 20
                }
            }
        ],
        "currency": "USD",
        "category": {
            "id": 1,
            "name": "Purchase"
        },
        "sub_category": {
            "id": 101,
            "name": "Raw Materials"
        }
    },
    "bank_transaction": {
        "id": 601,
        "datetime": "2023-04-15T14:30:00+00:00",
        "value": 12.00,
        "account": "Main Checking Account",
        "payment_method": "bank transfer"
    }
}

# The 'document_id' field is used when creating a 'transaction' to link it to the bill