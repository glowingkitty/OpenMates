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

def get_contact_address_categories() -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving contact address categories from SevDesk ...")

        # Get the directory where the script is running
        script_dir = os.path.dirname(os.path.realpath(__file__))
        file_path = os.path.join(script_dir, "contact_address_categories.json")

        # Check if the JSON file exists
        if os.path.exists(file_path):
            with open(file_path, "r") as file:
                return json.load(file)

        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = 'https://my.sevdesk.de/api/v1/Category?objectType=ContactAddress'
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            contact_address_categories = response.json()["objects"]

            # Save the result to a JSON file
            with open(file_path, "w") as file:
                json.dump(contact_address_categories, file,indent=4)

            add_to_log(f"Successfully retrieved contact address categories.", state="success")
            return contact_address_categories
        else:
            process_error(f"Failed to retrieve contact address categories, status code: {response.status_code}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to get contact address categories from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    get_contact_address_categories()
    