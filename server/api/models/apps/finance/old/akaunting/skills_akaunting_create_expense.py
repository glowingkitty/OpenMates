


from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Optional
from server.api.models.apps.akaunting.helper.skills_akaunting_create_vendor import VendorInfo
from server.api.models.apps.akaunting.helper.skills_akaunting_create_bill import BillInfo
from server.api.models.apps.akaunting.helper.skills_akauting_create_bank_transaction import BankTransactionInfo


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

class AkauntingCreateExpenseOutput(AkauntingCreateExpenseInput):
    pass


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