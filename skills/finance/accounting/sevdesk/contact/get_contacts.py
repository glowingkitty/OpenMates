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

def get_contacts() -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving contacts from SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        parameters = {
            "depth": "1" #Enum: "0", "1". Defines if both organizations and persons should be returned. '0' -> only organizations, '1' -> organizations and persons
        }
        url = 'https://my.sevdesk.de/api/v1/Contact'
        
        response = requests.get(url, headers=headers, params=parameters)
        if response.status_code == 200:
            contacts = response.json()["objects"]
            add_to_log(f"Successfully retrieved contacts.", state="success")
            return contacts
        else:
            process_error(f"Failed to retrieve contacts, status code: {response.status_code}")
            return {}
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to get contacts from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    # save the contact positions to a file
    contacts = get_contacts()
    with open("contacts.json", "w") as f:
        json.dump(contacts, f, indent=4)
    print("contacts.json")