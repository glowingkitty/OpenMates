# get_all_new_bank_transactions.py

################

# Default Imports

################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.banks.revolut_business.get_latest_transactions import get_latest_transactions
import json


def get_all_latest_bank_transactions(
        days: int = 2,
        start: str = None,
        end: str = None,
        use_existing_file_if_exists: bool = False,
        include_all: bool = False,
        unify_output: bool = True
        ) -> list:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Retrieving all new bank transactions ...")

        # TODO if new transaction which is complete is found, add it to accounting and and local json
        # TODO if a transaction with status reversed is found, search for it in accounting and delete it (and local json)
        # TODO enable filtering results from file

        # Load accounts from file if it exists
        if use_existing_file_if_exists:
            folder_path = f"{main_directory}temp_data/finance"
            os.makedirs(folder_path, exist_ok=True)
            file_path = f"{folder_path}/bank_transactions.json"
            if os.path.isfile(file_path):
                with open(file_path, 'r') as infile:
                    transactions = json.load(infile)
                add_to_log(f"Successfully loaded existing bank_transactions.json (ignored filters)", state="success")
                return transactions
        
        profile_details = load_profile_details()
        all_transactions = []
        
        for account in profile_details.get('bank_accounts', []):
            if account.get('bank') == "Revolut Business":
                latest_transactions = get_latest_transactions(
                    days=days,
                    start=start,
                    end=end,
                    use_existing_file_if_exists=use_existing_file_if_exists,
                    unify_output=unify_output,
                    include_all=include_all
                    )
                if latest_transactions:
                    all_transactions.extend(latest_transactions)
        
        add_to_log(f"Successfully retrieved all new bank transactions ({len(all_transactions)} total). Filtered as requested.", state="success")
        return all_transactions
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to get all new bank transactions", traceback=traceback.format_exc())
        return []

if __name__ == "__main__":
    transactions = get_all_latest_bank_transactions(
        start="2021-01-01",
        end="2024-01-04",
        # use_existing_file_if_exists=True
        )
    
    # save to file in temp folder
    folder_path = f"{main_directory}temp_data/finance"
    file_path = f"{folder_path}/bank_transactions.json"
    os.makedirs(folder_path, exist_ok=True)
    with open(file_path, 'w') as outfile:
        json.dump(transactions, outfile, indent=4)
    add_to_log(f"Saved all new bank transactions to {folder_path}/bank_transactions.json", state="success")