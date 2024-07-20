import os
from dotenv import load_dotenv
import requests
from server.api.models.skills.akaunting.skills_akaunting_create_income import AkauntingCreateIncomeOutput

load_dotenv()

async def create_income(
    token: str,
    customer: dict,
    invoice: dict,
    bank_transaction: dict
) -> AkauntingCreateIncomeOutput:
    """Create a new income in Akaunting"""
    
    # Load Akaunting API credentials
    akaunting_api_url = os.getenv("AKAUNTING_API_URL")
    akaunting_api_key = os.getenv("AKAUNTING_API_KEY")
    
    # Create customer if not exists
    customer_response = requests.post(
        f"{akaunting_api_url}/customers",
        headers={"Authorization": f"Bearer {akaunting_api_key}"},
        json=customer
    )
    customer_id = customer_response.json()["data"]["id"]
    
    # Create invoice
    invoice["customer_id"] = customer_id
    invoice_response = requests.post(
        f"{akaunting_api_url}/sales/invoices",
        headers={"Authorization": f"Bearer {akaunting_api_key}"},
        json=invoice
    )
    invoice_id = invoice_response.json()["data"]["id"]
    
    # Create bank transaction
    bank_transaction["document_id"] = invoice_id
    bank_transaction_response = requests.post(
        f"{akaunting_api_url}/banking/transactions",
        headers={"Authorization": f"Bearer {akaunting_api_key}"},
        json=bank_transaction
    )
    
    if customer_response.status_code == 201 and invoice_response.status_code == 201 and bank_transaction_response.status_code == 201:
        return AkauntingCreateIncomeOutput(success=True, message="Sales created successfully")
    else:
        return AkauntingCreateIncomeOutput(success=False, message="Failed to create sales")