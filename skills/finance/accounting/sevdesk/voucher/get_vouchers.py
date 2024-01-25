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

from datetime import datetime, timezone
from skills.finance.accounting.sevdesk.voucher.get_voucher_accounting_types import get_voucher_accounting_types

def get_vouchers(
        status: str = None,
        start_date: str = None,
        end_date: str = None,
        accounting_type: str = None,
        include_accounting_types: bool = False
        ) -> list:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving vouchers from SevDesk ...")
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        url = 'https://my.sevdesk.de/api/v1/Voucher'

        parameters = {"limit": 10000}

        if status is not None:
            if status == "paid":
                parameters["status"] = "1000"
            elif status == "partially_paid":
                parameters["status"] = "750"
            elif status == "transferred":
                parameters["status"] = "150"
            elif status == "unpaid":
                parameters["status"] = "100"
            elif status == "draft":
                parameters["status"] = "50"
        
        response = requests.get(url, headers=headers, params=parameters)
        if response.status_code == 200:
            vouchers = response.json()["objects"]

            if start_date is not None:
                # filter out by parsed voucherDate
                start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                
                vouchers = [voucher for voucher in vouchers if datetime.strptime(voucher["payDate"], '%Y-%m-%dT%H:%M:%S%z').astimezone(timezone.utc) >= start_date]

            if end_date is not None:
                # filter out by parsed voucherDate
                end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                
                vouchers = [voucher for voucher in vouchers if datetime.strptime(voucher["payDate"], '%Y-%m-%dT%H:%M:%S%z').astimezone(timezone.utc) <= end_date]
            
            if include_accounting_types or accounting_type is not None:
                for voucher in vouchers:
                    voucher["accounting_types"] = get_voucher_accounting_types(voucher["id"])

            if accounting_type is not None:
                if not isinstance(accounting_type, list):
                    accounting_types = [accounting_type]
                else:
                    accounting_types = accounting_type
                
                # check if any of the accounting types are in the voucher
                vouchers = [voucher for voucher in vouchers if any([str(accounting_type) in voucher["accounting_types"] for accounting_type in accounting_types])]
            
            add_to_log(f"Successfully retrieved vouchers ({len(vouchers)})", state="success")

            return vouchers
        else:
            process_error(f"Failed to retrieve vouchers, Status code: {response.status_code}, Response: {response.text}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to get vouchers from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import subprocess
    
    # save the voucher positions to a file
    vouchers = get_vouchers(
        status="paid",
        start_date="2023-04-01",
        end_date="2023-04-30"
    )
    # print(len(vouchers))
    with open("vouchers.json", "w") as f:
        json.dump(vouchers, f, indent=4)
    subprocess.run(["code", "vouchers.json"])