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

# https://api.sevdesk.de/#tag/Contact/operation/createContact


def add_contact(
        name: str = None,
        surename: str = None,
        familyname: str = None,
        category: str = "supplier", 
        **kwargs) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Creating contact in SevDesk ...")

        # set the contact details
        contact_details = {}
        for key, value in kwargs.items():
            contact_details[key] = value
        
        if name:
            contact_details["name"] = name
        if surename:
            contact_details["surename"] = surename
        if familyname:
            contact_details["familyname"] = familyname
        if category:
            contact_details["category"] = category

        # define contact category
        if contact_details.get("category") == "supplier":
            category_id = 2
        elif contact_details.get("category") == "customer":
            category_id = 3
        else:
            raise ValueError(f"Invalid category: {category}")
        
        contact_details["category"] = {
            "id": category_id,
            "objectName": "Category"
        }

        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {'Authorization': api_key, 'Content-Type': 'application/json'}
        url = 'https://my.sevdesk.de/api/v1/Contact'

        response = requests.post(url, headers=headers, data=json.dumps(contact_details))
        if response.status_code == 201:
            contact = response.json()["objects"]
            add_to_log(f"Successfully created contact.", state="success")
            return contact
        else:
            process_error(f"Failed to create contact, Status code: {response.status_code}: {response.text}")
            return {}
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to add contacts from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    # save the contact positions to a file
    contact = add_contact(surename="Vorname",familyname="Lastname", category="customer")
    with open("contact.json", "w") as f:
        json.dump(contact, f, indent=4)
    print("contact.json")