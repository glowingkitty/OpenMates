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

from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions


def delete_all_transactions(bank_account: str = None) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Delete all transactions ...")

        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Define the API endpoint
        api_endpoint = "https://my.sevdesk.de/api/v1/CheckAccountTransaction/"

        headers = {
            "Authorization": api_key
        }

        # get all transactions
        successfull_deletions = 0
        while True:
            transactions = get_transactions(bank_account=bank_account)
            count_transactions = len(transactions)
            failed_delete_attempts = 0
            if count_transactions == 0:
                break

            # delete all transactions
            for i, transaction in enumerate(transactions, start=1):
                response = requests.delete(api_endpoint+transaction["id"], headers=headers)
                if response.status_code == 200:
                    add_to_log(f"({i} of {count_transactions}) Successfully deleted transaction {transaction['id']}", state="success", module_name="SevDesk")
                    successfull_deletions += 1
                    
                else:
                    add_to_log(f"({i} of {count_transactions}) Failed to delete transaction {transaction['id']}", state="error", module_name="SevDesk")
                    failed_delete_attempts += 1
                    if failed_delete_attempts == count_transactions:
                        if successfull_deletions > 0:
                            add_to_log(f"Successfully deleted {successfull_deletions} transactions", state="success", module_name="SevDesk")
                            return True
                        else:
                            add_to_log(f"Could not delete any transactions", state="error", module_name="SevDesk")
                            return False
        
    except Exception:
        process_error("Failed to delete a transaction", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    delete_all_transactions()