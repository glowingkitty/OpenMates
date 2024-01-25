################

# Default Imports

################
import sys
import os
import re
import csv
import json
import datetime

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

def import_csv_data(filepath: str, bank_account_name: str) -> bool:
    try:
        add_to_log(module_name="CSV Import", color="yellow", state="start")
        add_to_log("Importing CSV data ...")

        # Load existing transactions
        folder_path = f"{main_directory}temp_data/finance"
        os.makedirs(folder_path, exist_ok=True)
        file_path = f"{folder_path}/bank_transactions.json"
        try:
            with open(file_path, 'r', encoding='utf-8') as json_file:
                transactions = json.load(json_file)
        except FileNotFoundError:
            transactions = []

        with open(filepath, mode='r', encoding='utf-8') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                # Combine date and time for created_at and completed_at
                completed_datetime = datetime.datetime.strptime(
                    f"{row['Completed date']} {row['Time completed']}", 
                    "%d.%m.%Y %H:%M"
                ).replace(microsecond=0).isoformat() + 'Z'
                
                transaction = {
                    "type": row["Transaction type"].lower().replace(" ", "_"),
                    "state": row["Status"].lower(),
                    "created_at": completed_datetime.replace('00Z', '00.000000Z'),
                    "updated_at": completed_datetime.replace('00Z', '00.000000Z'),
                    "completed_at": completed_datetime,
                    "merchant_name": row["Counterparty name"],
                    "legs": [
                        {
                            "amount": float(row["Payment amount"]),
                            "currency": row["Payment currency"],
                            "description": row["Reference"],
                            "balance": float(row["Wallet balance after transaction"])
                        }
                    ],
                    "card_number": row["Card number"],
                    "bank_account": bank_account_name
                }

                # Add bill_amount and bill_currency only if they are different from amount and currency
                if row["Payment currency"] != row["Original currency"]:
                    transaction["legs"][0]["bill_amount"] = float(row["Original amount"])
                    transaction["legs"][0]["bill_currency"] = row["Original currency"]

                # remove fields that are empty
                for field in list(transaction.keys()):
                    if not transaction[field] or transaction[field] == "":
                        del transaction[field]

                # Check if transaction already exists
                if transaction not in transactions:
                    transactions.append(transaction)

        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(transactions, json_file, ensure_ascii=False, indent=4)

        add_to_log("CSV data successfully imported into JSON.", state="success")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to import CSV data", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    filepath = os.path.join(os.path.dirname(__file__), 'finom_bank_transactions.csv')
    import_csv_data(filepath,bank_account_name="Finom")
