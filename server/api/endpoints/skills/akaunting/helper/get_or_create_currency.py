import os
import requests
from dotenv import load_dotenv
import base64

load_dotenv()

def get_or_create_currency(currency_code: str):
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
        for currency in currencies:
            if currency['code'] == currency_code:
                return currency

    # If currency doesn't exist, create it
    create_url = f"{base_url}/api/currencies"
    currency_data = {
        'name': currency_code,
        'code': currency_code,
        'rate': 1,
        'precision': 2,
        'symbol': currency_code,
        'symbol_first': 0,
        'decimal_mark': '.',
        'thousands_separator': ',',
        'enabled': 1
    }

    response = requests.post(create_url, headers=headers, json=currency_data)

    if response.status_code != 201:
        print(f"Error creating currency: {response.text}")
        return None

    created_currency = response.json().get('data')
    if not created_currency:
        print(f"Currency creation response doesn't contain 'data': {response.json()}")
        return None

    return created_currency

# Test function
def test_get_or_create_currency():
    currencies_to_test = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'CNY']

    for currency_code in currencies_to_test:
        print(f"\nTesting with {currency_code}:")
        currency = get_or_create_currency(currency_code)
        print(f"{currency_code} Currency:", currency)


if __name__ == "__main__":
    test_get_or_create_currency()