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

from skills.finance.banks.get_all_latest_bank_transactions import get_all_latest_bank_transactions
from skills.finance.accounting.sevdesk.banking.transaction.add_transaction import add_transaction


def send_new_bank_transactions_to_accounting(
        days: int = 2,
        start: str = None,
        end: str = None,
        bank_account_name: str = None,
        use_existing_file_if_exists: bool = False
        ) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Sending all new bank transactions to accounting ...")

        # TODO check for reverted transactions and delete them from accounting

        # get all the latest bank transactions
        bank_transactions = get_all_latest_bank_transactions(
            days=days,
            start=start,
            end=end,
            use_existing_file_if_exists=use_existing_file_if_exists
            )
        
        # then send the transactions to accounting
        for transaction in bank_transactions:
            if bank_account_name and transaction.get("bank_account") != bank_account_name:
                continue

            for leg in transaction["legs"]:
                # if both a description and reference are available, use them both
                if leg.get("description") and transaction.get("reference"):
                    payment_purpose = f"{leg.get('description')} - {transaction.get('reference')}"
                elif leg.get("description") and transaction.get("merchant_name"):
                    payment_purpose = f"{transaction.get('merchant_name')} - {leg.get('description')}"
                elif leg.get("description"):
                    payment_purpose = leg.get("description")
                elif transaction.get("reference"):
                    payment_purpose = transaction.get("reference")
                elif transaction.get("merchant_name"):
                    payment_purpose = transaction.get("merchant_name")
                else:
                    payment_purpose = "Transaction without description or reference"

                # if fees occured, add them to the amount
                if leg.get("fee"):
                    amount = leg["amount"] - leg["fee"]
                else:
                    amount = leg["amount"]

                add_transaction(
                    bank_account=transaction.get("bank_account"),
                    value_date=transaction.get("completed_at"),
                    entry_date=transaction.get("created_at"),
                    payment_purpose=payment_purpose,
                    amount=amount,
                    payee_payer_name=transaction.get("merchant_name"),
                    status="created"
                )

        
        add_to_log(f"Successfully sent all new bank transactions to accounting", state="success")
        return True
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to send all new bank transactions to accounting", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    send_new_bank_transactions_to_accounting(
        start="2023-12-01",
        # end="2023-03-15",
        # bank_account_name="Finom",
        # days=180
        # use_existing_file_if_exists=True
        )