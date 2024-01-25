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

import json


def get_user_already_asked_for_manual_processing(transaction: dict) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log(f"Checking for transaction '{transaction}'if user was already asked via chat to manually upload voucher PDF into accounting system ...")

        # TODO in future replace this with checking strapi for the transaction

        # load json file and check if the transaction ID is already in there
        json_file_path = f"{main_directory}temp_data/finance/accounting/transactions_user_was_asked_to_process_manually.json"

        # check if the file exists. If not, return False
        if not os.path.isfile(json_file_path):
            add_to_log("Transaction list could not be found. Therefore user was not asked via chat to manually upload voucher PDF into accounting system.")
            return False
        
        # else load the file and check if the transaction ID is in there
        with open(json_file_path, "r") as json_file:
            data = json.load(json_file)
            for json_transaction in data['transactions']:
                if json_transaction['id'] == transaction['id']:
                    add_to_log("User was already asked via chat to manually upload voucher PDF into accounting system.")
                    return True
                
        return False

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to check if user was already asked via chat for voucher PDF", traceback=traceback.format_exc())
        return False