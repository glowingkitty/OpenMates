################

# Default Imports

################
import sys
import os
import re
import requests
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.accounting.sevdesk.contact.search_country import search_country

# https://api.sevdesk.de/#tag/ContactAddress/operation/createContactAddress


def add_contact_address(
        contact_id: str,
        street: str = None,
        zip: str = None,
        city: str = None,
        country_code: str = None,
        name: str = None,
        name2: str = None
        ) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Creating contact address in SevDesk ...")

        # set the contact address details 
        if not contact_id or contact_id == "":
            raise ValueError(f"Invalid contact_id: {contact_id}")
        
        # at least one of the following fields must be set
        if not street and not zip and not city and not country_code and not name and not name2:
            add_to_log(f"Failed to create contact address. At least one of the following fields must be set: street, zip, city, country_code, name, name2", state="error")
            return None

        contact_address_details = {
            "contact": {
                "id": contact_id,
                "objectName": "Contact"
            }
        }
        
        if street:
            contact_address_details["street"] = street
        if zip:
            contact_address_details["zip"] = zip
        if city:
            contact_address_details["city"] = city
        if country_code:
            # find the country based on the country code
            country = search_country(country_code)
            if country:
                contact_address_details["country"] = {
                    "id": country["id"],
                    "objectName": "StaticCountry"
                }
        if name:
            contact_address_details["name"] = name
        if name2:
            contact_address_details["name2"] = name2

        # add category "invoice address"
        contact_address_details["category"] = {
            "id": 47,
            "objectName": "Category"
        }

        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {'Authorization': api_key, 'Content-Type': 'application/json'}
        url = 'https://my.sevdesk.de/api/v1/ContactAddress'

        response = requests.post(url, headers=headers, data=json.dumps(contact_address_details))
        if response.status_code == 201:
            contact_address = response.json()
            add_to_log(f"Successfully created contact address.", state="success")
            return contact_address
        else:
            process_error(f"Failed to create contact address, Status code: {response.status_code}: {response.text}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to add contact address from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    contact_address = add_contact_address(
        contact_id="",
        street="Test street 13",
        zip="10992",
        city="Berlin",
        country_code="DE",
        name="Max Mustermann",
        name2="Muellermann Ehrlichmann"
    )