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

from enum import Enum

class TransactionStatus(Enum):
    CREATED = 100
    LINKED = 200
    PRIVATE = 300
    BOOKED = 400

def update_transaction(
        id: int,
        value_date: str = None,
        entry_date: str = None,
        payment_purpose: str = None,
        amount: float = None,
        payee_payer_name: str = None,
        check_account_id: int = None,
        status: TransactionStatus = None,
        enshrined: str = None,
        source_transaction_id: int = None,
        target_transaction_id: int = None) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Updating a transaction ...")

        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Define the API endpoint
        api_endpoint = f"https://my.sevdesk.de/api/v1/CheckAccountTransaction/{id}"

        headers = {
            "Authorization": api_key
        }

        # Prepare the request payload
        transaction_data = {}

        if value_date is not None:
            transaction_data["valueDate"] = value_date
        if entry_date is not None:
            transaction_data["entryDate"] = entry_date
        if payment_purpose is not None:
            transaction_data["paymtPurpose"] = payment_purpose
        if amount is not None:
            transaction_data["amount"] = amount
        if payee_payer_name is not None:
            transaction_data["payeePayerName"] = payee_payer_name
        if check_account_id is not None:
            transaction_data["checkAccount"] = {
                "objectName": "CheckAccount",
                "id": check_account_id
            }
        if status is not None:
            transaction_data["status"] = status.value if isinstance(status, TransactionStatus) else status
        if enshrined is not None:
            transaction_data["enshrined"] = enshrined
        if source_transaction_id is not None:
            transaction_data["sourceTransaction"] = {
                "id": source_transaction_id,
                "objectName": "CheckAccountTransaction"
            }
        if target_transaction_id is not None:
            transaction_data["targetTransaction"] = {
                "id": target_transaction_id,
                "objectName": "CheckAccountTransaction"
            }

        # Make the PUT request
        response = requests.put(api_endpoint, json=transaction_data, headers=headers)

        # Check for successful response
        if response.status_code == 200:
            add_to_log(f"Transaction successfully updated with ID: {id}", state="success")
            return True
        else:
            error_message = response.json().get('error', {}).get('message', 'Unknown error')
            error_code = response.json().get('error', {}).get('code', 'Unknown code')
            process_error(f"Failed to update transaction. Status code: {response.status_code}, Error code: {error_code}, Error message: {error_message}")
            return False

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to update a transaction", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    ids = [1632666296,1632666301,1632666247,1632474114]
    for id in ids:
        update_transaction(
            id=id,
            status=TransactionStatus.CREATED)