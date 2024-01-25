################

# Default Imports

################
import sys
import os
import re
import requests
from datetime import datetime, timedelta

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.banks.revolut_business.authentification.get_access_token import get_access_token
import json
from datetime import time

# https://developer.revolut.com/docs/business/get-transactions

def get_latest_transactions(
        days: int = 2, 
        start: str = None,
        end: str = None,
        use_existing_file_if_exists: bool = False,
        unify_output: bool = True,
        include_all: bool = False,
        exclude_reverted_transactions: bool = True,
        exclude_internal_transactions: bool = True,
        exclude_declined_transactions: bool = True,
        exclude_zero_amount_transactions: bool = True,
        save_excluded_transactions_to_file: bool = False
        ) -> list:
    try:
        add_to_log(module_name="Revolut Business", color="blue", state="start")
        add_to_log("Fetching the latest transactions ...")

        # TODO for every new transaction, check if it already exists in bank_transactions.json. If not, add it to the json file.

        # check if the start and end dates are valid
        if start:
            try:
                start_date = datetime.strptime(start, '%Y-%m-%d')
            except:
                raise ValueError("Incorrect start date format, should be YYYY-MM-DD")
        if end:
            try:
                end_date = datetime.strptime(end, '%Y-%m-%d')
            except:
                raise ValueError("Incorrect end date format, should be YYYY-MM-DD")
        else:
            end_date = datetime.now()

        # Check if the requested timeframe is longer than 90 days
        if days > 90 or (start and (end_date - start_date).days > 90):
            add_to_log(f"Requested timeframe is longer than 90 days. Because of PSD2 SCA regulations, this can only be done in the first 5 minutes of authorization of a new token. Requesting a new access token ...")
            get_access_token(restart_auth_flow=True)

        # Load transactions from file if it exists
        if use_existing_file_if_exists:
            folder_path = f"{main_directory}temp_data/finance/revolut_business"
            file_path = f"{folder_path}/transactions.json"
            os.makedirs(folder_path, exist_ok=True)
            if os.path.isfile(file_path):
                with open(file_path, 'r') as infile:
                    transactions = json.load(infile)
                add_to_log(f"Successfully loaded existing transactions.json", state="success")
                return transactions

        # Define the endpoint URL for transactions
        url = "https://b2b.revolut.com/api/1.0/transactions"
        
        # Prepare the headers with the authorization token
        access_token = get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        # Define a time range for the transactions
        if start and end:
            since_date = datetime.strptime(start, '%Y-%m-%d').isoformat() + 'Z'  # ISO 8601 format
            till_date = datetime.combine(datetime.strptime(end, '%Y-%m-%d'), time(23, 59, 59))
            if till_date > datetime.now():
                till_date = None
            else:
                till_date = till_date.isoformat() + 'Z'  # ISO 8601 format
        elif start:
            since_date = datetime.strptime(start, '%Y-%m-%d').isoformat() + 'Z'  # ISO 8601 format
            till_date = datetime.combine(end_date, time(23, 59, 59))
            if till_date > datetime.now():
                till_date = None
            else:
                till_date = till_date.isoformat() + 'Z'  # ISO 8601 format
        else:
            since_date = (datetime.now() - timedelta(days=days)).isoformat(timespec='seconds') + 'Z'  # ISO 8601 format
            till_date = datetime.now().isoformat(timespec='seconds') + 'Z'  # ISO 8601 format
        
        # define the parameters
        params = {
            "from": since_date, 
            "to": till_date,
            "count": 1000
            }

        # Make the API request
        response = requests.get(url, headers=headers, params=params)

        # Initialize a list to store excluded transactions
        excluded_transactions = []
        
        # Check if the request was successful
        if response.status_code == 200:
            transactions = response.json()

            if not include_all:
                # exclude reverted transactions
                if exclude_reverted_transactions:
                    add_to_log(f"Excluding reverted transactions ...")
                    before_count = len(transactions)
                    if save_excluded_transactions_to_file:
                        excluded_transactions.extend([transaction for transaction in transactions if transaction["state"] == "reverted"])
                    transactions = [transaction for transaction in transactions if transaction["state"] != "reverted"]
                    after_count = len(transactions)
                    add_to_log(f"Excluded {before_count - after_count} reverted transactions. {after_count} transactions left.")

                # exclude declined transactions
                if exclude_declined_transactions:
                    add_to_log(f"Excluding declined transactions ...")
                    before_count = len(transactions)
                    if save_excluded_transactions_to_file:
                        excluded_transactions.extend([transaction for transaction in transactions if transaction["state"] == "declined"])
                    transactions = [transaction for transaction in transactions if transaction["state"] != "declined"]
                    after_count = len(transactions)
                    add_to_log(f"Excluded {before_count - after_count} declined transactions. {after_count} transactions left.")
                
                # exclude zero amount transactions
                if exclude_zero_amount_transactions:
                    add_to_log(f"Excluding zero amount transactions ...")
                    before_count = len(transactions)
                    if save_excluded_transactions_to_file:
                        excluded_transactions.extend([transaction for transaction in transactions if transaction["legs"][0]["amount"] == 0])
                    transactions = [transaction for transaction in transactions if transaction["legs"][0]["amount"] != 0]
                    after_count = len(transactions)
                    add_to_log(f"Excluded {before_count - after_count} zero amount transactions. {after_count} transactions left.")

                if exclude_internal_transactions:
                    add_to_log(f"Excluding internal transactions ...")
                    # remove all transactions that have two entries in "legs" and they cancel each other out
                    filtered_transactions = []
                    before_count = len(transactions)
                    if save_excluded_transactions_to_file:
                        excluded_transactions.extend([transaction for transaction in transactions if len(transaction["legs"]) == 2 and transaction["legs"][0]["amount"] + transaction["legs"][1]["amount"] == 0])

                    for transaction in transactions:
                        if len(transaction["legs"]) == 1:
                            filtered_transactions.append(transaction)
                        elif len(transaction["legs"]) == 2:
                            if transaction["legs"][0]["amount"] + transaction["legs"][1]["amount"] != 0:
                                filtered_transactions.append(transaction)
                    transactions = filtered_transactions
                    after_count = len(transactions)
                    add_to_log(f"Excluded {before_count - after_count} internal transactions. {after_count} transactions left.")

                if save_excluded_transactions_to_file:
                    # Save excluded transactions to a file
                    excluded_file_path = "excluded_transactions.json"
                    with open(excluded_file_path, 'w') as outfile:
                        json.dump(excluded_transactions, outfile, indent=4)
                    add_to_log(f"Saved excluded transactions to {excluded_file_path}", state="success")
                
            # unify the output
            if unify_output:
                add_to_log(f"Unifying the output ...")
                unified_transactions = []

                # check if the transaction details exist, if so, add them to the transaction
                transaction_details = [
                    ["id", "id"],
                    ["type", "type"],
                    ["state", "state"],
                    ["created_at", "created_at"],
                    ["updated_at", "updated_at"],
                    ["completed_at", "completed_at"],
                    ["scheduled_for", "scheduled_for"],
                    ["merchant_name", "merchant|name"],
                    ["reference", "reference"],
                    ["legs", "legs"],
                    ["card_number", "card|card_number"],
                    ["revertable", "revertable"]
                ]

                for transaction in transactions:
                    output_transaction = {}
                    for transaction_detail in transaction_details:
                        keys = transaction_detail[1].split("|")
                        temp = transaction
                        for key in keys:
                            if isinstance(temp, list):
                                temp = temp[int(key)]
                            else:
                                temp = temp.get(key, None)
                            if temp is None:
                                break
                        if temp is not None:
                            output_transaction[transaction_detail[0]] = temp
                    unified_transactions.append(output_transaction)
                        
                transactions = unified_transactions

                # add "bank_account" field as well
                for transaction in transactions:
                    transaction["bank_account"] = "Revolut Business"

            add_to_log(f"Successfully fetched the transactions for the requested time: {len(transactions)} transactions", state="success")
            return transactions
        else:
            process_error(f"Failed to fetch transactions for the requested time. Status code: {response.status_code}: {response.text}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to get the latest transactions for the requested time.", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    transactions = get_latest_transactions(90, use_existing_file_if_exists=True)
    
    # save to file in temp folder
    folder_path = f"{main_directory}temp_data/finance/revolut_business"
    file_path = f"{folder_path}/transactions.json"
    os.makedirs(folder_path, exist_ok=True)
    if not os.path.isfile(file_path):
        with open(f'{folder_path}/transactions.json', 'w') as outfile:
            json.dump(transactions, outfile, indent=4)
        add_to_log(f"Saved transactions to {folder_path}/transactions.json", state="success")