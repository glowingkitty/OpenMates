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

from server.api import *
################


import os
from dotenv import load_dotenv
import requests
from server.api.models.apps.akaunting.helper.skills_akaunting_create_vendor import VendorInfo, AkauntingCreateVendorOutput
from server.api.endpoints.apps.akaunting.helper.get_or_create_currency import get_or_create_currency
import base64

load_dotenv()

async def create_vendor(vendor_data: VendorInfo) -> AkauntingCreateVendorOutput:
    """Create a new vendor in Akaunting"""
    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    endpoint = f"{base_url}/api/contacts"

    # Check and create currency if needed
    get_or_create_currency(currency_data={'code': vendor_data.currency_code})

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
            'name': vendor_dict['name'],
            'email': vendor_dict['email'],
            'tax_number': vendor_dict['tax_number'],
            'currency_code': vendor_dict['currency_code'],
            'phone': vendor_dict['phone'],
            'website': vendor_dict['website'],
            'address': vendor_dict['address'],
            'city': vendor_dict['city'],
            'zip_code': vendor_dict['zip_code'],
            'state': vendor_dict['state'],
            'country': vendor_dict['country'],
            'reference': vendor_dict['reference'],
            'enabled': vendor_dict['enabled']
        }

        return AkauntingCreateVendorOutput(**output_data)

    except requests.RequestException as e:
        error_message = f"Error creating vendor in Akaunting: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nStatus code: {e.response.status_code}"
            error_message += f"\nResponse content: {e.response.text}"
        print(error_message)
        raise Exception(error_message)