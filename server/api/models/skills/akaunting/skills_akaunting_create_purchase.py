from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional
import re
from datetime import datetime

class VendorInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of an existing vendor")
    name: str = Field(..., description="The name of the vendor")
    email: Optional[str] = Field(None, description="The email of the vendor")
    phone: Optional[str] = Field(None, description="The phone number of the vendor")
    tax_number: Optional[str] = Field(None, description="The tax number of the vendor")
    currency: str = Field(..., description="The currency used by the vendor")
    address: Optional[str] = Field(None, description="The address of the vendor")
    city: Optional[str] = Field(None, description="The city of the vendor")
    zip_code: Optional[str] = Field(None, description="The ZIP code of the vendor")
    state: Optional[str] = Field(None, description="The state of the vendor")
    country: Optional[str] = Field(None, description="The country of the vendor")
    website: Optional[str] = Field(None, description="The website of the vendor")
    reference: Optional[str] = Field(None, description="The reference for the vendor")

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

class TaxInfo(BaseModel):
    name: str = Field(..., description="The name of the tax")
    rate: float = Field(..., description="The rate of the tax")

    @field_validator('rate')
    @classmethod
    def validate_rate(cls, v):
        if v < 0 or v > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {v}")
        return v

class ItemInfo(BaseModel):
    name: str = Field(..., description="The name of the item")
    description: Optional[str] = Field(None, description="The description of the item")
    quantity: int = Field(..., description="The quantity of the item")
    price: float = Field(..., description="The price of the item")
    tax: Optional[TaxInfo] = Field(None, description="The tax information for the item")

    @field_validator('quantity')
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError(f"Quantity must be greater than 0: {v}")
        return v

    @field_validator('price')
    @classmethod
    def validate_price(cls, v):
        if v < 0:
            raise ValueError(f"Price cannot be negative: {v}")
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
    name: str = Field(..., description="The name of the category")
    parent_category: Optional[str] = Field(None, description="The parent category, if any")

class BillInfo(BaseModel):
    date: str = Field(..., description="The date of the bill (ISO 8601 format: YYYY-MM-DD)")
    due_date: str = Field(..., description="The due date of the bill (ISO 8601 format: YYYY-MM-DD)")
    order_number: Optional[str] = Field(None, description="The order number, if any")
    items: List[ItemInfo] = Field(..., description="List of items in the bill")
    discount: Optional[DiscountInfo] = Field(None, description="Discount information, if any")
    currency: str = Field(..., description="The currency of the bill")
    currency_convert_rate_to_default_currency: Optional[float] = Field(None, description="Conversion rate to default currency, if different")
    notes: Optional[str] = Field(None, description="Additional notes for the bill")
    category: CategoryInfo = Field(..., description="The category of the bill")
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
        if len(v) != 3:
            raise ValueError(f"Currency code must be 3 characters long: {v}")
        return v.upper()

class BankTransactionInfo(BaseModel):
    date: str = Field(..., description="The date of the bank transaction (ISO 8601 format: YYYY-MM-DD)")
    value: float = Field(..., description="The value of the bank transaction")
    account: str = Field(..., description="The bank account for the transaction")

    @field_validator('date')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {v}")
        return v

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        if v <= 0:
            raise ValueError(f"Transaction value must be greater than 0: {v}")
        return v

class AkauntingCreatePurchaseInput(BaseModel):
    vendor: VendorInfo = Field(..., description="Information about the vendor")
    bill: BillInfo = Field(..., description="Information about the bill")
    bank_transaction: BankTransactionInfo = Field(..., description="Information about the bank transaction")

    model_config = ConfigDict(extra="forbid")

# Update the example to match the new structure
akaunting_create_purchase_input_example = {
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
                "price": 10.00,
                "tax": {
                    "name": "Sales Tax",
                    "rate": 20
                }
            }
        ],
        "currency": "USD",
        "category": {
            "name": "Supplies"
        }
    },
    "bank_transaction": {
        "date": "2023-04-15",
        "value": 12.00,
        "account": "Main Checking Account"
    }
}

class AkauntingCreatePurchaseOutput(BaseModel):
    id: int = Field(..., description="The ID of the created purchase")
    vendor: VendorInfo = Field(..., description="Vendor information")
    bill: BillInfo = Field(..., description="Bill information")
    bank_transaction: BankTransactionInfo = Field(..., description="Bank transaction information")


akaunting_create_purchase_output_example = {
    "id": 1,
    "vendor": {
        "id": 1,
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
                "price": 10.00,
                "tax": {
                    "name": "Sales Tax",
                    "rate": 20
                }
            }
        ],
        "currency": "USD",
        "category": {
            "name": "Supplies"
        }
    },
    "bank_transaction": {
        "date": "2023-04-15",
        "value": 12.00,
        "account": "Main Checking Account"
    }
}

# The 'document_id' field is used when creating a 'transaction' to link it to the bill
