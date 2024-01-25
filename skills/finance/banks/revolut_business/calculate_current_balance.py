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


def calculate_current_balance(filepath:str) -> float:
    try:
        add_to_log(module_name="Revolut Business", color="blue", state="start")
        add_to_log("Calculating current balance ...")

        # check if file exists
        if not os.path.isfile(filepath):
            add_to_log(f"File {filepath} does not exist", state="error")
            return None
        
        balance = 0
        money_transfers = 0

        # load all transactions
        with open(filepath, 'r') as infile:
            transactions = json.load(infile)

            # for every transaction, for every item in the list ["legs"], add the "amount", (-)"fee" (if it exists) and (-)"tax" (if it exists) to the balance
            for transaction in transactions:
                if len(transaction.get("legs", [])) == 2:
                    add_to_log(f"Transaction with two legs found: {transaction.get('id')}")
                for leg in transaction.get("legs", []):
                    money_transfers += 1
                    balance += leg.get("amount", 0)
                    balance -= leg.get("fee", 0)
        

        add_to_log(f"Successfully calculated current balance: {round(balance,2)}. From {money_transfers} money transfers", state="success")
        return balance
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to calculate current balance", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    filepath = f"{main_directory}temp_data/finance/revolut_business/bank_transactions.json"
    calculate_current_balance(filepath)