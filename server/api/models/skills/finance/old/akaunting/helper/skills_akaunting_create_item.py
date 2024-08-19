################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


from pydantic import BaseModel, Field, field_validator
from typing import Optional


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
    net_price: float = Field(..., description="The net price of the item")
    tax: Optional[TaxInfo] = Field(None, description="The tax information for the item, if applicable")

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