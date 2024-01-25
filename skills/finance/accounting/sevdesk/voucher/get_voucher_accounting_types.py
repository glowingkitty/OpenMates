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

# more details: https://github.com/Pommespanzer/sevdesk-php-client/blob/master/docs/Api/VoucherApi.md

def get_voucher_accounting_types(voucher_id: str = None) -> list:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving voucher accounting types from SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = f'https://my.sevdesk.de/api/v1/Voucher/{voucher_id}/getAccountingTypes'

        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            accounting_types = response.json()["objects"]
            accounting_type_ids = [accounting_type["id"] for accounting_type in accounting_types]
            add_to_log(f"Successfully retrieved voucher accounting types.", state="success")
            return accounting_type_ids
        else:
            process_error(f"Failed to get voucher accounting types from SevDesk API", traceback=traceback.format_exc())
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to get voucher accounting types from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    ids = get_voucher_accounting_types("99129292")
    print(ids)