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


def get_all_accounts(use_existing_file_if_exists: bool = False) -> list:
    try:
        add_to_log(module_name="Revolut Business", color="blue", state="start")
        add_to_log("Fetching all accounts ...")

        # Load accounts from file if it exists
        if use_existing_file_if_exists:
            folder_path = f"{main_directory}temp_data/finance/revolut_business"
            file_path = f"{folder_path}/accounts.json"
            os.makedirs(folder_path, exist_ok=True)
            if os.path.isfile(file_path):
                with open(file_path, 'r') as infile:
                    transactions = json.load(infile)
                add_to_log(f"Successfully loaded existing accounts.json", state="success")
                return transactions

        # Define the endpoint URL for accounts
        url = "https://b2b.revolut.com/api/1.0/accounts"
        
        # Prepare the headers with the authorization token
        access_token = get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        # Make the API request
        response = requests.get(url, headers=headers)
        
        # Check if the request was successful
        if response.status_code == 200:
            accounts = response.json()
            add_to_log(f"Successfully fetched all accounts: {len(accounts)} accounts", state="success")
            return accounts
        else:
            process_error(f"Failed to fetch accounts. Status code: {response.status_code}: {response.text}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to get all accounts. Error: {str(e)}", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    accounts = get_all_accounts(use_existing_file_if_exists=True)

    # save to file in temp folder
    folder_path = f"{main_directory}temp_data/finance/revolut_business"
    file_path = f"{folder_path}/accounts.json"
    os.makedirs(folder_path, exist_ok=True)
    if not os.path.isfile(file_path):
        with open(f'{folder_path}/accounts.json', 'w') as outfile:
            json.dump(accounts, outfile, indent=4)
        add_to_log(f"Saved accounts to {folder_path}/accounts.json", state="success")