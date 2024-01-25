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

from skills.finance.accounting.sevdesk.banking.check_account.get_check_accounts import get_check_accounts
from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions

def add_transaction(
        bank_account: str,                  # Name of the bank account
        value_date: str,                    # example 01.01.2022, Date the check account transaction was booked
        entry_date: str,                    # example 01.01.2022, Date the check account transaction was imported
        payment_purpose: str,               # the purpose of the transaction
        amount: float,                      # Amount of the transaction
        payee_payer_name: str,              # Name of the payee/payer
        status: str = "created",            # Status of the transaction (100 <-> Created, 200 <-> Linked, 300 <-> Private, 400 <-> Booked)
        enshrined: str = None,              # example 2019-08-24T14:15:22Z, Defines if the transaction has been enshrined and can not be changed any more.
        source_transaction_id: int = None,  # ID of The check account transaction serving as the source of the rebooking
        target_transaction_id: int = None   # ID of The check account transaction serving as the target of the rebooking
        ) -> str:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Adding a new transaction ...")

        # search first if the transaction already exists, if so, return the id
        found_transaction = get_transactions(
            bank_account=bank_account,
            payment_purpose=payment_purpose,
            start_date=value_date,
            end_date=value_date,
            payee_payer_name=payee_payer_name,
            amount=amount
        )
        if found_transaction:
            transaction_id = found_transaction[0].get("id")
            add_to_log(f"Transaction already exists with ID: {transaction_id}", state="success")
            return found_transaction[0]

        # set the status
        if status.lower() == "booked" or status.lower() == "completed":
            status = 400
        elif status.lower() == "linked":
            status = 200
        elif status.lower() == "private":
            status = 300
        else:
            status = 100 # created


        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Define the API endpoint
        api_endpoint = "https://my.sevdesk.de/api/v1/CheckAccountTransaction"

        headers = {
            "Authorization": api_key
        }

        # fint the check account id based on the bank account name
        check_account_id = None
        check_accounts = get_check_accounts()
        for check_account in check_accounts:
            if check_account.get("name") == bank_account:
                check_account_id = check_account.get("id")
                break

        # Prepare the request payload
        transaction_data = {
            "valueDate": value_date,
            "entryDate": entry_date,
            "paymtPurpose": payment_purpose,
            "amount": amount,
            "payeePayerName": payee_payer_name,
            "checkAccount": {
                "id": check_account_id,
                "objectName": "CheckAccount"
            },
            "status": status
        }

        # Optional fields
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

        # Make the POST request
        response = requests.post(api_endpoint, json=transaction_data, headers=headers)

        # Check for successful response
        if response.status_code == 201:
            id = response.json().get("objects").get("id")
            add_to_log(f"Transaction successfully added with ID: {id}", state="success")
            return response.json()
        else:
            process_error(f"Failed to add transaction. Status code: {response.status_code}, Response: {response.text}", state="error")
            return None
        

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to add a new transaction", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    add_transaction(
        value_date="2023-11-28",
        entry_date="2023-11-28",
        payment_purpose="card_payment",
        amount=-9.11,
        payee_payer_name="GitHub",
        bank_account="Revolut Business",
    )