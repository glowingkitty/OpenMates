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
from server.api.models.skills.akaunting.skills_akaunting_create_vendor import AkauntingCreateVendorInput, AkauntingCreateVendorOutput
import base64

load_dotenv()

async def create_vendor(vendor_data: AkauntingCreateVendorInput) -> AkauntingCreateVendorOutput:
    """Create a new vendor in Akaunting"""
    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    endpoint = f"{base_url}/api/contacts"

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/json',
        'X-Company': os.getenv('AKAUNTING_COMPANY_ID'),
    }

    # Prepare query parameters
    params = {
        'search': 'type:vendor',
        'type': 'vendor',  # Add this line
        **vendor_data.model_dump(exclude_unset=True)
    }

    # Print the full URL with parameters for debugging
    full_url = requests.Request('POST', endpoint, params=params).prepare().url
    print(f"Sending request to: {full_url}")

    try:
        response = requests.post(endpoint, headers=headers, params=params)
        print(f"Response status code: {response.status_code}")
        print(f"Response content: {response.content}")
        response.raise_for_status()
        vendor_data = response.json()['data']

        # Create the output object with all input data plus the new ID
        output_data = {**vendor_data.model_dump(), 'id': vendor_data['id']}
        return AkauntingCreateVendorOutput(**output_data)
    except requests.RequestException as e:
        print(f"Error response content: {e.response.content if hasattr(e, 'response') else 'No response content'}")
        raise Exception(f"Error creating vendor in Akaunting: {str(e)}")
    

if __name__ == "__main__":
    import asyncio
    print(asyncio.run(create_vendor(AkauntingCreateVendorInput(
        name="Test Vendor",
        email="test@vendor.com",
        tax_number="1234567890",
        currency_code="USD",
        enabled=1,
        phone="1234567890",
        website="http://testvendor.com",
        address="123 Test St, Test City, Test Country"
    ))))