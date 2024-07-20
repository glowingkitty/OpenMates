from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional
import re

# Define a set of valid currency codes (you can expand this list as needed)
VALID_CURRENCIES = {'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR'}

class AkauntingCreateVendorInput(BaseModel):
    name: str = Field(..., description="The name of the vendor")
    currency_code: str = Field(..., description="The currency code for the vendor")
    email: Optional[str] = Field(None, description="The email of the vendor")
    tax_number: Optional[str] = Field(None, description="The tax number of the vendor")
    phone: Optional[str] = Field(None, description="The phone number of the vendor")
    website: Optional[str] = Field(None, description="The website of the vendor")
    address: Optional[str] = Field(None, description="The address of the vendor")
    enabled: int = Field(1, description="Whether the vendor is enabled (1) or disabled (0)")
    reference: Optional[str] = Field(None, description="A reference for the vendor")

    model_config = ConfigDict(extra="forbid")

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid email format: {v}")
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is not None:
            # This pattern allows for more flexible phone number formats
            pattern = r'^\+?[1-9]\d{1,14}$'
            # Remove any non-digit characters except the leading +
            cleaned_number = '+' + ''.join(filter(str.isdigit, v)) if v.startswith('+') else ''.join(filter(str.isdigit, v))
            if not re.match(pattern, cleaned_number):
                raise ValueError(f"Invalid phone number format: {v}")
            return cleaned_number
        return v

    @field_validator('website')
    @classmethod
    def validate_website(cls, v):
        if v is not None:
            pattern = r'^https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)$'
            if not re.match(pattern, v):
                raise ValueError(f"Invalid website URL format: {v}")
        return v

    @field_validator('currency_code')
    @classmethod
    def validate_currency(cls, v):
        if v.upper() not in VALID_CURRENCIES:
            raise ValueError(f"Invalid currency code: {v}")
        return v.upper()

    @field_validator('enabled')
    @classmethod
    def validate_enabled(cls, v):
        if v not in [0, 1]:
            raise ValueError(f"Enabled must be 0 or 1: {v}")
        return v

class AkauntingCreateVendorOutput(AkauntingCreateVendorInput):
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