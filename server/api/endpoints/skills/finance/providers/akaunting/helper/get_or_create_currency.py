################
# Default Imports
################
import sys
import os
import re
from typing import Union, Dict

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import os
import requests
from dotenv import load_dotenv
import base64
from server.api.models.skills.akaunting.helper.skills_akaunting_create_currency import CurrencyInfo, AkauntingCurrencyOutput

load_dotenv()

def get_or_create_currency(currency_data: Union[CurrencyInfo, Dict]) -> AkauntingCurrencyOutput:
    if isinstance(currency_data, dict):
        # if no name and / or no symbol is provided, use the code as the name and symbol
        if not currency_data.get('name'):
            currency_data['name'] = currency_data['code']
        if not currency_data.get('symbol'):
            currency_data['symbol'] = currency_data['code']
        currency_info = CurrencyInfo(**currency_data)
    elif isinstance(currency_data, CurrencyInfo):
        currency_info = currency_data
    else:
        raise ValueError("Input must be either a CurrencyInfo object or a dictionary")

    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/json',
        'X-Company': os.getenv('AKAUNTING_COMPANY_ID'),
    }

    # Check if currency exists
    get_url = f"{base_url}/api/currencies"
    response = requests.get(get_url, headers=headers)

    if response.status_code == 200:
        currencies = response.json().get('data', [])
        for existing_currency in currencies:
            if existing_currency['code'] == currency_info.code:
                found_currency = {
                    'id': existing_currency['id'],
                    'name': existing_currency['name'],
                    'code': existing_currency['code'],
                    'rate': existing_currency['rate'],
                    'precision': existing_currency['precision'],
                    'symbol': existing_currency['symbol'],
                    'symbol_first': existing_currency['symbol_first'],
                    'decimal_mark': existing_currency['decimal_mark'],
                    'thousands_separator': existing_currency['thousands_separator'],
                    'enabled': existing_currency['enabled']
                }
                return AkauntingCurrencyOutput(**found_currency)

    # If currency doesn't exist, create it
    create_url = f"{base_url}/api/currencies"
    currency_data = currency_info.model_dump()

    response = requests.post(create_url, headers=headers, json=currency_data)

    if response.status_code != 201:
        raise ValueError(f"Error creating currency: {response.text}")

    created_currency = response.json().get('data')
    if not created_currency:
        raise ValueError(f"Currency creation response doesn't contain 'data': {response.json()}")

    formate_currency = {
        'id': created_currency['id'],
        'name': created_currency['name'],
        'code': created_currency['code'],
        'rate': created_currency['rate'],
        'precision': created_currency['precision'],
        'symbol': created_currency['symbol'],
        'symbol_first': created_currency['symbol_first'],
        'decimal_mark': created_currency['decimal_mark'],
        'thousands_separator': created_currency['thousands_separator'],
        'enabled': created_currency['enabled']
    }
    return AkauntingCurrencyOutput(**formate_currency)