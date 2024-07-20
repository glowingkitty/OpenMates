from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional
import re

# Define a set of valid currency codes (you can expand this list as needed)
VALID_CURRENCIES = {'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR'}

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


class AkauntingCreateVendorOutput(VendorInfo):
    id: int = Field(..., description="The ID of the created vendor")


# Example input
akaunting_create_vendor_input_example = {
    "name": "Acme Supplies",
    "email": "contact@acmesupplies.com",
    "tax_number": "123456789",
    "currency_code": "USD",
    "phone": "+1234567890",
    "website": "https://www.acmesupplies.com",
    "address": "123 Supply St, Vendor City, VC 12345",
    "reference": "ACME001"
}

# Example output
akaunting_create_vendor_output_example = {
    "id": 1001,
    "name": "Acme Supplies",
    "email": "contact@acmesupplies.com",
    "tax_number": "123456789",
    "currency_code": "USD",
    "phone": "+1234567890",
    "website": "https://www.acmesupplies.com",
    "address": "123 Supply St, Vendor City, VC 12345",
    "enabled": 1,
    "reference": "ACME001"
}