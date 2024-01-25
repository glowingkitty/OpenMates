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

import requests

def delete_transaction(id: int) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Delete a transaction ...")

        # Load the API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Define the API endpoint
        api_endpoint = f"https://my.sevdesk.de/api/v1/CheckAccountTransaction/{id}"

        headers = {
            "Authorization": api_key
        }

        # Send the DELETE request
        response = requests.delete(api_endpoint, headers=headers)

        # Check for successful response
        if response.status_code == 200:
            add_to_log(f"Transaction successfully deleted with ID: {id}", state="success")
            return True
        else:
            error_message = response.json().get('error', {}).get('message', 'Unknown error')
            error_code = response.json().get('error', {}).get('code', 'Unknown code')
            process_error(f"Failed to delete transaction. Status code: {response.status_code}, Error code: {error_code}, Error message: {error_message}")
            return False

    except Exception:
        process_error("Failed to delete a transaction", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    ids = [1632668961]
    for id in ids:
        delete_transaction(id=id)