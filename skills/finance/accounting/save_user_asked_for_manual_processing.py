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


def save_user_asked_for_manual_processing(transaction: dict) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Saving that user was asked via chat to manually upload voucher PDF into accounting system ...")

        # TODO in future replace this with checking strapi for the transaction
        
        # load json file and save the transaction ID in there
        json_file_path = f"{main_directory}temp_data/finance/accounting/transactions_user_was_asked_to_process_manually.json"

        # if the file exists, load it and add the transaction ID to the list
        if os.path.isfile(json_file_path):
            with open(json_file_path, "r") as json_file:
                data = json.load(json_file)
                data['transactions'].append(transaction)

        # else create the file and add the transaction ID to the list
        else:
            data = {
                "transactions": [
                    transaction
                ]
            }

        # save the file
        # if the filepath does not exist, create it
        if not os.path.exists(os.path.dirname(json_file_path)):
            os.makedirs(os.path.dirname(json_file_path))
        with open(json_file_path, "w") as json_file:
            json.dump(data, json_file)

        add_to_log("Successfully saved that user was asked via chat to manually upload voucher PDF into accounting system")
        return True

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to save that user was asked via chat for voucher PDF", traceback=traceback.format_exc())
        return False