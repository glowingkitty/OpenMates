from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional
from datetime import datetime


class Counterparty(BaseModel):
    account_id: Optional[str] = Field(None, title="Counterparty Account ID", description="The ID of the counterparty account")
    account_type: Optional[str] = Field(None, title="Counterparty Account Type", description="The type of the counterparty account")

class Merchant(BaseModel):
    name: Optional[str] = Field(None, title="Merchant Name", description="The name of the merchant")
    city: Optional[str] = Field(None, title="Merchant City", description="The city where the merchant is located")
    category_code: Optional[str] = Field(None, title="Merchant Category Code", description="The category code of the merchant")

class Transaction(BaseModel):
    id: str = Field(..., title="Transaction ID", description="Unique identifier for the transaction")
    type: str = Field(..., title="Transaction Type", description="The type of the transaction")
    status: str = Field(..., title="Status", description="The current status of the transaction")
    created_at: datetime = Field(..., title="Created At", description="The date and time when the transaction was created")
    updated_at: datetime = Field(..., title="Updated At", description="The date and time when the transaction was last updated")
    completed_at: Optional[datetime] = Field(None, title="Completed At", description="The date and time when the transaction was completed")
    amount: float = Field(..., title="Amount", description="The transaction amount")
    currency: str = Field(..., title="Currency", description="The currency of the transaction")
    description: str = Field(..., title="Description", description="A description of the transaction")
    account_id: str = Field(..., title="Account ID", description="The ID of the account associated with the transaction")
    counterparty: Counterparty = Field(..., title="Counterparty", description="Information about the counterparty")
    merchant: Merchant = Field(..., title="Merchant", description="Information about the merchant")
    card_last_four: Optional[str] = Field(None, title="Card Last Four", description="The last four digits of the card used in the transaction")
    cardholder_name: Optional[str] = Field(None, title="Cardholder Name", description="The name of the cardholder")

class FinanceGetTransactionsInput(BaseModel):
    from_date: str = Field(..., title="From Date", description="Start date for transactions (format: YYYY-MM-DD)")
    to_date: str = Field(..., title="To Date", description="End date for transactions (format: YYYY-MM-DD)")
    bank: str = Field(..., title="Bank", description="The bank name")
    account: str = Field(..., title="Account", description="The account name")
    count: int = Field(..., title="Count", description="How many results to return")
    type: Optional[str] = Field(None, title="Transaction Type", description="Transaction type. Possible values: [atm, card_payment, card_refund, card_chargeback, card_credit, exchange, transfer, loan, fee, refund, topup, topup_return, tax, tax_refund]")

    model_config = ConfigDict(extra="forbid")

    @field_validator('bank')
    @classmethod
    def validate_bank(cls, v):
        if v not in ['Revolut Business']:
            raise ValueError("Invalid bank. Needs to be 'Revolut Business'.")
        return v


class FinanceGetTransactionsOutput(BaseModel):
    transactions: List[Transaction] = Field(..., title="Transactions", description="List of transactions matching the query")

finance_get_transactions_input_example = {
    "from_date": "2023-01-01",
    "to_date": "2023-12-31",
    "bank": "Revolut Business",
    "account": "Main Account",
    "count": 100,
    "type": "card_payment"
}

finance_get_transactions_output_example = {
    "transactions": [
        {
            "id": "tx_00000000000000000000a",
            "type": "card_payment",
            "status": "completed",
            "created_at": "2023-06-01T10:00:00Z",
            "updated_at": "2023-06-01T10:01:00Z",
            "completed_at": "2023-06-01T10:01:00Z",
            "amount": -50.00,
            "currency": "EUR",
            "description": "Coffee Shop",
            "account_id": "acc_00000000000000000000a",
            "counterparty": {
                "account_id": None,
                "account_type": None
            },
            "merchant": {
                "name": "Local Coffee Shop",
                "city": "Berlin",
                "category_code": "5814"
            },
            "card_last_four": "1234",
            "cardholder_name": "John Doe"
        }
    ]
}