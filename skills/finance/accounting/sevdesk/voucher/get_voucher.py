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


def get_voucher(voucher_id: int) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log(f"Retrieving voucher with ID {voucher_id} from SevDesk ...")

        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = f'https://my.sevdesk.de/api/v1/Voucher/{voucher_id}'

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            voucher = response.json()["objects"]
            if len(voucher) == 0:
                process_error(f"Failed to retrieve voucher with ID {voucher_id}, because it does not exist.")
                return None
            voucher = voucher[0]
            add_to_log(f"Successfully retrieved voucher with ID {voucher_id}.", state="success")
            return voucher
        else:
            process_error(f"Failed to retrieve voucher with ID {voucher_id}, Status code: {response.status_code}, Response: {response.text}")
            return None

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to get voucher with ID {voucher_id} from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import json
    import subprocess

    voucher = get_voucher(voucher_id="")
    with open('voucher.json', 'w') as f:
        json.dump(voucher, f, indent=4)
    subprocess.run(["code", "voucher.json"])