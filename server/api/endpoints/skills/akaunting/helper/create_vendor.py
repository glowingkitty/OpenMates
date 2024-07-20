################
# Default Imports
################
import sys
import os
import re
from urllib.parse import urlencode

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


import os
from dotenv import load_dotenv
import requests
from server.api.models.skills.akaunting.helper.skills_akaunting_create_vendor import VendorInfo, AkauntingCreateVendorOutput
from server.api.endpoints.skills.akaunting.helper.get_or_create_currency import get_or_create_currency
import base64

load_dotenv()

async def create_vendor(vendor_data: VendorInfo) -> AkauntingCreateVendorOutput:
    """Create a new vendor in Akaunting"""
    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    endpoint = f"{base_url}/api/contacts"

    # Check and create currency if needed
    get_or_create_currency(vendor_data.currency_code)

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'X-Company': os.getenv('AKAUNTING_COMPANY_ID'),
    }

    # Convert vendor_data to a dictionary and remove the 'id' field
    vendor_dict = vendor_data.model_dump(exclude={'id'})
    vendor_dict['type'] = 'vendor'
    vendor_dict['enabled'] = vendor_dict.get('enabled')

    # Construct the URL with query parameters
    query_string = urlencode(vendor_dict)
    url = f"{endpoint}?search=type:vendor&{query_string}"

    try:
        response = requests.post(url, headers=headers)
        response.raise_for_status()

        # Parse the response JSON
        response_data = response.json()['data']

        # Create the output object
        output_data = {
            'id': response_data['id'],
            'name': response_data['name'],
            'email': response_data.get('email'),
            'tax_number': response_data.get('tax_number'),
            'currency_code': response_data.get('currency_code'),
            'phone': response_data.get('phone'),
            'website': response_data.get('website'),
            'address': response_data.get('address'),
            'city': response_data.get('city'),
            'zip_code': response_data.get('zip_code'),
            'state': response_data.get('state'),
            'country': response_data.get('country'),
            'reference': response_data.get('reference'),
            'enabled': response_data.get('enabled')
        }

        output_data = {k: v for k, v in output_data.items() if v is not None and v != 'None'}

        return AkauntingCreateVendorOutput(**output_data)
    except requests.RequestException as e:
        error_message = f"Error creating vendor in Akaunting: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nStatus code: {e.response.status_code}"
            error_message += f"\nResponse content: {e.response.text}"
        print(error_message)
        raise Exception(error_message)


if __name__ == "__main__":
    import asyncio

    # Additional examples
    test_vendors = [
        VendorInfo(
            name="Global Tech Solutions Inc.",
            email="info@globaltechsolutions.com",
            tax_number="98-7654321",
            currency_code="USD",
            phone="+16505550123",
            website="https://www.globaltechsolutions.com",
            address="1 Infinite Loop",
            city="Cupertino",
            zip_code="95014",
            state="CA",
            country="US",
            reference="GTS-2023-001"
        ),
        VendorInfo(
            name="Berlin Precision Engineering GmbH",
            email="kontakt@berlinengineering.de",
            tax_number="DE123456789",
            currency_code="EUR",
            phone="+493012345678",
            website="https://www.berlinengineering.de",
            address="Unter den Linden 10",
            city="Berlin",
            zip_code="10117",
            state="Berlin",
            country="DE",
            reference="BPE-2023-001"
        ),
        VendorInfo(
            name="Sydney Green Energy Pty Ltd",
            email="info@sydneygreenenergy.com.au",
            tax_number="12 345 678 901",
            currency_code="AUD",
            phone="+61298765432",
            website="https://www.sydneygreenenergy.com.au",
            address="200 George Street",
            city="Sydney",
            zip_code="2000",
            state="NSW",
            country="AU",
            reference="SGE-2023-001"
        )
    ]

    for vendor in test_vendors:
        result = asyncio.run(create_vendor(vendor))
        print(f"Created vendor: {result}")