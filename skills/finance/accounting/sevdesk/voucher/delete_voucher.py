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

from skills.finance.accounting.sevdesk.voucher.get_voucher import get_voucher
from skills.finance.accounting.sevdesk.voucher.update_voucher import update_voucher

def delete_voucher(voucher_id: str) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Deleting voucher from SevDesk ...")

        # get the voucher and check if the status is 50 (draft)
        voucher = get_voucher(voucher_id=voucher_id)

        # if the voucher status is 1000 (booked), we cannot delete it
        if voucher.get("status") == "1000":
            process_error(f"Failed to delete voucher with ID {voucher_id}, because it is already booked.")
            return False
        
        # if the voucher status is 100 (open), we need to change the status first to 50 (draft)
        elif voucher.get("status") == "100":
            add_to_log(f"Voucher with ID {voucher_id} is open, changing status to draft first.")
            success = update_voucher(voucher_id=voucher_id, voucher_data={"status": 50})
            if not success:
                add_to_log(f"Failed to delete voucher with ID {voucher_id}, because it could not be set to draft status.")
                return False

        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = f'https://my.sevdesk.de/api/v1/Voucher/{voucher_id}'
        
        response = requests.delete(url, headers=headers)
        if response.status_code == 200:
            add_to_log(f"Successfully deleted voucher.", state="success")
            return True
        else:
            process_error(f"Failed to delete voucher, Status code: {response.status_code}, Response: {response.text}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to delete voucher", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    delete_voucher(voucher_id="75976245")