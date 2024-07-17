from pydantic import BaseModel, Field, ConfigDict
from typing import List

class VendorInfo(BaseModel):
    name: str = Field(..., description="The name of the vendor")
    address: str = Field(..., description="The address of the vendor")
    country: str = Field(..., description="The country of the vendor")

class ItemInfo(BaseModel):
    name: str = Field(..., description="The name of the item")
    price: float = Field(..., description="The price of the item")
    vat: float = Field(..., description="The VAT amount for the item")
    total: float = Field(..., description="The total amount for the item")
    quantity: int = Field(..., description="The quantity of the item")

class AkauntingCreatePurchaseInput(BaseModel):
    vendor: VendorInfo = Field(..., description="Information about the vendor")
    items: List[ItemInfo] = Field(..., description="List of items in the purchase")

    model_config = ConfigDict(extra="forbid")

akaunting_create_purchase_input_example = {
    "vendor": {
        "name": "Acme Corp",
        "address": "123 Main St, Anytown, AN 12345",
        "country": "United States"
    },
    "items": [
        {
            "name": "Widget",
            "price": 10.00,
            "vat": 2.00,
            "total": 12.00,
            "quantity": 1
        }
    ]
}

class AkauntingCreatePurchaseOutput(BaseModel):
    success: bool = Field(..., description="Whether the purchase was created successfully")
    purchase_id: int = Field(..., description="The ID of the created purchase")

akaunting_create_purchase_output_example = {
    "success": True,
    "purchase_id": 12345
}