"""Shared first-party invoice address shape for Personal and Team billing."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class BuyerAddress(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    street_line_1: str = Field(min_length=1, max_length=160)
    street_line_2: Optional[str] = Field(default=None, max_length=160)
    postal_code: str = Field(min_length=1, max_length=32)
    city: str = Field(min_length=1, max_length=100)
    region: Optional[str] = Field(default=None, max_length=100)
    country: str = Field(min_length=2, max_length=2)
    vat_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        if not value.isalpha() or not value.isascii():
            raise ValueError("country must be an ISO alpha-2 code")
        return value.upper()


class BuyerAddressRequest(BaseModel):
    buyer_address: Optional[BuyerAddress] = None
