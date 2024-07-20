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
from server.api.models.skills.akaunting.skills_akaunting_create_expense import BillInfo
from server.api.endpoints.skills.akaunting.helper.get_or_create_currency import get_or_create_currency
import base64

load_dotenv()

async def create_bill(bill_data: BillInfo) -> BillInfo:
    """Create a new bill in Akaunting"""
    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    endpoint = f"{base_url}/api/documents"

    # Check and create currency if needed
    get_or_create_currency(currency_data={'code':bill_data.currency})

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'X-Company': os.getenv('AKAUNTING_COMPANY_ID'),
    }

    # Convert bill_data to a dictionary
    bill_dict = bill_data.model_dump(exclude_none=True)
    bill_dict['type'] = 'bill'

    # TODO:
    # - category_id instead of category (name)
    # - include search=type:bill
    # - include status=draft
    # - include account_id

    # Construct the URL with query parameters
    query_string = urlencode(bill_dict, doseq=True)
    url = f"{endpoint}?{query_string}"

    try:
        response = requests.post(url, headers=headers)
        response.raise_for_status()

        # Parse the response JSON
        response_data = response.json()['data']

        # Create the output object
        created_bill = BillInfo(**response_data)

        return created_bill

    except requests.RequestException as e:
        error_message = f"Error creating bill in Akaunting: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nStatus code: {e.response.status_code}"
            error_message += f"\nResponse content: {e.response.text}"
        print(error_message)
        raise Exception(error_message)


if __name__ == "__main__":
    import asyncio
    from server.api.models.skills.akaunting.helper.skills_akaunting_create_item import ItemInfo

    result = asyncio.run(create_bill(BillInfo(
        date="2023-04-15",
        due_date="2023-05-15",
        category={"name": "Purchase"},
        items=[
            ItemInfo(name="Widget", quantity=1, net_price=10.00)
        ],
        currency="USD",
    )))
    print(f"Created bill: {result}")