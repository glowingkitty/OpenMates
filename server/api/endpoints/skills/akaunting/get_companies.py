import os
from dotenv import load_dotenv
import requests
from typing import Dict, Any
import base64

load_dotenv()

async def get_companies() -> Dict[str, Any]:
    """Get the list of companies from Akaunting"""
    base_url = os.getenv('AKAUNTING_API_URL')
    username = os.getenv('AKAUNTING_USERNAME')
    password = os.getenv('AKAUNTING_PASSWORD')

    if not all([base_url, username, password]):
        raise ValueError("Missing required environment variables for Akaunting API")

    endpoint = f"{base_url}/api/companies"

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise Exception(f"Error fetching companies from Akaunting: {str(e)}")
    

if __name__ == "__main__":
    import asyncio
    print(asyncio.run(get_companies()))