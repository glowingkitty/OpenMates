################

# Default Imports

################
import sys
import os
import re
import requests

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

def delete_contact(contact_id: str) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Deleting contact in SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = f'https://my.sevdesk.de/api/v1/Contact/{contact_id}'
        
        response = requests.delete(url, headers=headers)
        if response.status_code == 200:
            add_to_log(f"Successfully deleted contact", state="success")
            return True
        else:
            process_error(f"Failed to delete contact, status code: {response.status_code}")
            return False
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to delete contact from SevDesk API", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    # save the contact positions to a file
    delete_contact()