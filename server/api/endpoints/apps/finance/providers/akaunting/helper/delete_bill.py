import os
from dotenv import load_dotenv
import requests
import base64

load_dotenv()

async def delete_bill(bill_id: int) -> dict:
    """Delete a bill in Akaunting"""
    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    endpoint = f"{base_url}/api/documents/{bill_id}"

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'X-Company': os.getenv('AKAUNTING_COMPANY_ID'),
    }

    try:
        response = requests.delete(endpoint, headers=headers, params={'type': 'bill'})

        if response.status_code == 404:
            return {
                'success': False,
                'message': f"No bill found with ID {bill_id}."
            }

        response.raise_for_status()

        # Create the output dictionary
        output_data = {
            'success': True,
            'message': f"Bill with ID {bill_id} has been successfully deleted."
        }

        return output_data

    except requests.RequestException as e:
        error_message = f"Error deleting bill in Akaunting: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nStatus code: {e.response.status_code}"
            error_message += f"\nResponse content: {e.response.text}"
        print(error_message)
        raise Exception(error_message)