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

def get_accounting_types() -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving accounting types from SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = 'https://my.sevdesk.de/api/v1/AccountingType'
        
        offset = 0
        all_accounting_types = []
        while True:
            params = {
                'offset': offset
            }
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                new_accounting_types = response.json()["objects"]
                all_accounting_types.extend(new_accounting_types)
                
                if len(new_accounting_types) < 100:
                    break
                offset += 100
            else:
                process_error(f"Failed to retrieve accounting types, Status code: {response.status_code}, Response: {response.text}")
                break
        
        add_to_log(f"Successfully retrieved all accounting types.", state="success")
        return all_accounting_types
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to get accounting types from SevDesk API", traceback=traceback.format_exc())
    
    
    
if __name__ == "__main__":
    accounting_types = get_accounting_types()
    with open("accounting_types.json", "w") as f:
        json.dump(accounting_types, f, indent=4)
    print("accounting_types.json")