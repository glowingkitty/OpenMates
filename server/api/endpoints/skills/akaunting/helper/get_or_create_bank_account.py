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


import os
from dotenv import load_dotenv
import requests
import base64
from urllib.parse import urlencode
from server.api.models.skills.akaunting.helper.skills_akaunting_create_bank_account import BankAccountInfo, AkauntingBankAccountOutput
from server.api.endpoints.skills.akaunting.helper.get_or_create_currency import get_or_create_currency
from typing import Union, Dict

load_dotenv()


def get_or_create_bank_account(bank_account_data: Union[BankAccountInfo, Dict]) -> AkauntingBankAccountOutput:
    """Get or create a bank account in Akaunting"""
    if isinstance(bank_account_data, dict):
        bank_account_data = BankAccountInfo(**bank_account_data)
    elif not isinstance(bank_account_data, BankAccountInfo):
        raise ValueError("bank_account_data must be an instance of BankAccountInfo or a dictionary")

    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')
    company_id = os.getenv('AKAUNTING_COMPANY_ID')

    if not all([base_url, username, password, company_id]):
        raise ValueError("Missing required environment variables for Akaunting API")

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'X-Company': company_id,
    }

    # Check and create currency if needed
    get_or_create_currency(currency_data={'code':bank_account_data.currency_code})

    # Check if account exists
    get_url = f"{base_url}/api/accounts"
    response = requests.get(get_url, headers=headers)
    if response.status_code == 200:
        accounts = response.json().get('data', [])
        for account in accounts:
            if account['name'] == bank_account_data.account_name:
                return AkauntingBankAccountOutput(**account)

    # If account doesn't exist, create it
    create_endpoint = f"{base_url}/api/accounts"
    account_data = {
        'type': 'bank',
        'name': bank_account_data.account_name,
        'number': bank_account_data.account_number,
        'currency_code': bank_account_data.currency_code,
        'opening_balance': bank_account_data.opening_balance,
        'bank_name': bank_account_data.bank_name,
        'bank_phone': bank_account_data.bank_phone,
        'bank_address': bank_account_data.bank_address,
        'enabled': bank_account_data.enabled
    }

    # Construct the URL with query parameters
    query_string = urlencode(account_data)
    url = f"{create_endpoint}?{query_string}"

    try:
        response = requests.post(url, headers=headers)
        response.raise_for_status()

        # Parse the response JSON
        created_account = response.json().get('data')
        if not created_account:
            raise Exception(f"Bank account creation response doesn't contain 'data': {response.json()}")

        output_data = {
            'id': created_account['id'],
            'account_name': bank_account_data.account_name,
            'account_number': bank_account_data.account_number,
            'currency_code': bank_account_data.currency_code,
            'opening_balance': bank_account_data.opening_balance,
            'bank_name': bank_account_data.bank_name,
            'bank_phone': bank_account_data.bank_phone,
            'bank_address': bank_account_data.bank_address,
            'enabled': bank_account_data.enabled
        }

        return AkauntingBankAccountOutput(**output_data)

    except requests.RequestException as e:
        error_message = f"Error creating bank account in Akaunting: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nStatus code: {e.response.status_code}"
            error_message += f"\nResponse content: {e.response.text}"
        print(error_message)
        raise Exception(error_message)

# Update the test function
def test_get_or_create_bank_account():
    accounts_to_test = [
        BankAccountInfo(
            account_name='Test Account 1',
            account_number='1234567890',
            currency_code='USD',
            opening_balance=1000,
            bank_name='My Bank',
            bank_address='Bank Address',
            bank_phone='1234567890'
        ),
        BankAccountInfo(
            account_name='Test Account 2',
            account_number='0987654321',
            currency_code='EUR',
            opening_balance=2000,
            bank_name='My Bank',
            bank_address='Bank Address',
            bank_phone='0987654321'
        ),
        BankAccountInfo(
            account_name='Test Account 3',
            account_number='1122334455',
            currency_code='GBP',
            opening_balance=3000,
            bank_name='My Bank',
            bank_address='Bank Address',
            bank_phone='1122334455'
        )
    ]

    for account_data in accounts_to_test:
        print(f"\nTesting with {account_data.account_name}:")
        account = get_or_create_bank_account(account_data)
        print(f"{account_data.account_name} Account:", account)

if __name__ == "__main__":
    test_get_or_create_bank_account()