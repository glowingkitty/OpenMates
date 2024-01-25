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


def update_voucher(voucher_id: str, voucher_data: dict) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Updating voucher in SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {'Authorization': api_key, 'Content-Type': 'application/json'}
        url = f'https://my.sevdesk.de/api/v1/Voucher/{voucher_id}'
        
        response = requests.put(url, headers=headers, data=json.dumps(voucher_data))
        if response.status_code == 200:
            voucher = response.json()["objects"]
            add_to_log(f"Successfully updated voucher.", state="success")
            return voucher
        else:
            process_error(f"Failed to update voucher, Status code: {response.status_code}, Response: {response.text}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to update voucher", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    update_voucher(voucher_id="", voucher_data={"status": 50})
