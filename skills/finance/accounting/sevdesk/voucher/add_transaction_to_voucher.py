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


def add_transaction_to_voucher(voucher_data: dict,transaction: dict) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Adding voucher to transaction ...")

        # make sure the voucher is present 
        if not voucher_data.get("voucher"):
            add_to_log("Voucher data is missing", state="error")
            return False
        
        # book the voucher to the transaction using the SevDesk API
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Save the voucher details to sevDesk
        headers = {'Authorization': api_key, 'Content-Type': 'application/json'}

        transaction_date_obj = datetime.fromisoformat(transaction["entryDate"])
        # Convert the datetime object to UTC
        transaction_date_obj_utc = transaction_date_obj.astimezone(timezone.utc)

        # Format the UTC datetime object back into a string
        transaction_date_str_utc = transaction_date_obj_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "amount": transaction["amount"],
            "date": transaction_date_str_utc,
            "type": "N",
            "checkAccount": {
                "id": transaction["checkAccount"]["id"],
                "objectName": "CheckAccount"
            },
            "checkAccountTransaction":{
                "id": transaction["id"],
                "objectName": "CheckAccountTransaction"
            },
            "createFeed": True
        }

        # "type":
        # Enum: "N" "CB" "CF" "O" "OF" "MTC"
        # Define a type for the booking.
        # The following type abbreviations are available (abbreviation <-> meaning).

        # N <-> Normal booking / partial booking
        # CB <-> Reduced amount due to discount (skonto)
        # CF <-> Reduced/Higher amount due to currency fluctuations
        # O <-> Reduced/Higher amount due to other reasons
        # OF <-> Higher amount due to reminder charges
        # MTC <-> Reduced amount due to the monetary traffic costs

        response = requests.put(f"https://my.sevdesk.de/api/v1/Voucher/{voucher_data['voucher']['id']}/bookAmount", headers=headers, data=json.dumps(data))
        if response.status_code != 200:
            process_error(f"Failed to add the voucher to the transaction. Status code: {response.status_code}: {response.text}")
            return False
        
        add_to_log(f"Successfully added the voucher ({voucher_data['voucher']['id']}) to the transaction ({transaction['id']})", state="success")

        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to add voucher to transaction", traceback=traceback.format_exc())
        return None

