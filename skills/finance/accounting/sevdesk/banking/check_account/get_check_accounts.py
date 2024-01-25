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

import json


def get_check_accounts() -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Getting all check accounts ...")

        # check if a json file with the check accounts exists. If so, return it
        folder_path = f"{main_directory}temp_data/finance/sevdesk"
        os.makedirs(folder_path, exist_ok=True)
        file_path = f"{folder_path}/check_accounts.json"
        if os.path.isfile(file_path):
            with open(file_path, "r") as file:
                check_accounts = json.load(file)
            add_to_log(f"Found a json file with the check accounts. Returning it.", state="success", module_name="SevDesk")
            return check_accounts

        # Load the API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Define the API endpoint
        api_endpoint = "https://my.sevdesk.de/api/v1/CheckAccount"

        # Set the headers
        headers = {
            "Authorization": api_key
        }

        # Make the GET request
        response = requests.get(api_endpoint, headers=headers)

        # Check for successful response
        if response.status_code == 200:
            check_accounts = response.json().get("objects", [])
            # save all check accounts to a file
            with open(file_path, 'w') as outfile:
                json.dump(check_accounts, outfile, indent=4)

            add_to_log(f"Successfully fetched all check accounts and saved them to {file_path}", state="success")
            return 
        else:
            process_error(f"Failed to get check accounts. Status code: {response.status_code}, Response: {response.text}")
            return None

    except Exception:
        process_error("Failed to get check accounts", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    accounts = get_check_accounts()
    print(accounts)