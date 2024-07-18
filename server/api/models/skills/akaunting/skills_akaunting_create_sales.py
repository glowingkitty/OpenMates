from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

class CustomerInfo(BaseModel):
    id: Optional[int] = Field(None, description="The ID of an existing customer")
    name: Optional[str] = Field(None, description="The name of the customer")
    address: Optional[str] = Field(None, description="The address of the customer")
    country: Optional[str] = Field(None, description="The country of the customer")

class ItemInfo(BaseModel):
    name: str = Field(..., description="The name of the item")
    price: float = Field(..., description="The price of the item")
    vat: float = Field(..., description="The VAT amount for the item")
    total: float = Field(..., description="The total amount for the item")
    quantity: int = Field(..., description="The quantity of the item")

class InvoiceInfo(BaseModel):
    date_time: str = Field(..., description="The date and time of the invoice (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
    items: List[ItemInfo] = Field(..., description="List of items in the invoice")

class BankTransactionInfo(BaseModel):
    date_time: str = Field(..., description="The date and time of the bank transaction (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
    value: float = Field(..., description="The value of the bank transaction")
    bank_account: str = Field(..., description="The bank account for the transaction")

class AkauntingCreateSalesInput(BaseModel):
    customer: CustomerInfo = Field(..., description="Information about the customer or customer ID")
    invoice: InvoiceInfo = Field(..., description="Information about the invoice")
    bank_transaction: BankTransactionInfo = Field(..., description="Information about the bank transaction")

    model_config = ConfigDict(extra="forbid")

class AkauntingCreateSalesOutput(BaseModel):
    id: int = Field(..., description="The ID of the created sale")
    customer: CustomerInfo = Field(..., description="Customer information")
    invoice: InvoiceInfo = Field(..., description="Invoice information")
    bank_transaction: BankTransactionInfo = Field(..., description="Bank transaction information")

akaunting_create_sales_input_example = {
    "customer": {
        "name": "John Doe",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "invoice": {
        "date_time": "2023-06-01T14:30:00Z",
        "items": [
            {
                "name": "Product A",
                "price": 100.00,
                "vat": 20.00,
                "total": 120.00,
                "quantity": 1
            }
        ]
    },
    "bank_transaction": {
        "date_time": "2023-06-01T14:35:00Z",
        "value": 120.00,
        "bank_account": "Main Checking Account"
    }
}

akaunting_create_sales_output_example = {
    "id": 1,
    "customer": {
        "id": 1,
        "name": "John Doe",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "invoice": {
        "date_time": "2023-06-01T14:30:00Z",
        "items": [
            {
                "name": "Product A",
                "price": 100.00,
                "vat": 20.00,
                "total": 120.00,
                "quantity": 1
            }
        ]
    },
    "bank_transaction": {
        "date_time": "2023-06-01T14:35:00Z",
        "value": 120.00,
        "bank_account": "Main Checking Account"
    }
}