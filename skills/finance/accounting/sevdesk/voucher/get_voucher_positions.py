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

def get_voucher_positions() -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving voucher positions from SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = 'https://my.sevdesk.de/api/v1/VoucherPos'

        parameters = {"limit": 10000}
        
        response = requests.get(url, headers=headers, params=parameters)
        if response.status_code == 200:
            voucher_positions = response.json()["objects"]
            add_to_log(f"Successfully retrieved voucher positions ({len(voucher_positions)})", state="success")
            return voucher_positions
        else:
            process_error(f"Failed to retrieve voucher positions, status code: {response.status_code}, response: {response.text}")
            return {}
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to get voucher positions from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import subprocess
    # save the voucher positions to a file
    voucher_positions = get_voucher_positions()
    with open("voucher_positions.json", "w") as f:
        json.dump(voucher_positions, f, indent=4)
    subprocess.run(["code", "voucher_positions.json"])