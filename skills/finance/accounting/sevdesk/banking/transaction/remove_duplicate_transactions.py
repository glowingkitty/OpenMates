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

from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions
from skills.finance.accounting.sevdesk.banking.transaction.delete_transaction import delete_transaction

def remove_duplicate_transactions(
        bank_account: str = None,               # Name of the bank account
        start_date: str = None,                 # example 01.01.2022 or 01/2022, the start date to search for transactions
        end_date: str = None,                   # example 31.01.2022 or 01/2022, the end date to search for transactions
    ) -> list:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Finding and removing duplicate transactions ...")

        # get all closed transactions
        closed_transactions = get_transactions(
            bank_account=bank_account,
            is_open=False,
            start_date=start_date,
            end_date=end_date
        )

        # get all open transactions
        open_transactions = get_transactions(
            bank_account=bank_account,
            is_open=True,
            start_date=start_date,
            end_date=end_date
        )

        # for every closed transaction, search in "open transactions" if it already exists with the same date, amount and purpose and payee/payer
        for closed_transaction in closed_transactions:
            for open_transaction in open_transactions:
                # check if the date, amount and purpose and payee/payer are the same
                if closed_transaction.get("id") != open_transaction.get("id") and \
                    float(closed_transaction.get("amount")) == float(open_transaction.get("amount")) and \
                    closed_transaction.get("paymtPurpose") == open_transaction.get("paymtPurpose") and \
                    closed_transaction.get("payeePayerName") == open_transaction.get("payeePayerName") and \
                    closed_transaction.get("valueDate") == open_transaction.get("valueDate") and \
                    closed_transaction.get("entryDate") == open_transaction.get("entryDate"):
                    # if yes, delete the open transaction
                    add_to_log(f"The open transaction with ID {open_transaction.get('id')} is a duplicate of the closed transaction with ID {closed_transaction.get('id')}. Deleting the open transaction.")
                    success = delete_transaction(open_transaction.get("id"))
                    if success:
                        add_to_log(f"Successfully deleted the open transaction with ID {open_transaction.get('id')}.", state="success")
                    else:
                        add_to_log(f"Failed to delete the open transaction with ID {open_transaction.get('id')}.", state="error")


        # get all open transactions
        open_transactions = get_transactions(
            bank_account=bank_account,
            is_open=True,
            start_date=start_date,
            end_date=end_date
        )

        # for every open transaction, search in "open transactions" if it already exists with the same date, amount and purpose and payee/payer
        for open_transaction in open_transactions:
            # for every transaction, check if there are one or multiple duplicates and delete all the duplicates (leaving only one)
            for open_transaction_duplicate in open_transactions:
                # check if the date, amount and purpose and payee/payer are the same
                if open_transaction.get("id") != open_transaction_duplicate.get("id") and \
                    float(open_transaction.get("amount")) == float(open_transaction_duplicate.get("amount")) and \
                    open_transaction.get("paymtPurpose") == open_transaction_duplicate.get("paymtPurpose") and \
                    open_transaction.get("payeePayerName") == open_transaction_duplicate.get("payeePayerName") and \
                    open_transaction.get("valueDate") == open_transaction_duplicate.get("valueDate") and \
                    open_transaction.get("entryDate") == open_transaction_duplicate.get("entryDate"):
                    # if yes, delete the open transaction
                    add_to_log(f"The open transaction with ID {open_transaction_duplicate.get('id')} is a duplicate of the open transaction with ID {open_transaction.get('id')}. Deleting the open transaction.")
                    success = delete_transaction(open_transaction_duplicate.get("id"))
                    if success:
                        add_to_log(f"Successfully deleted the open transaction with ID {open_transaction_duplicate.get('id')}.", state="success")
                    else:
                        add_to_log(f"Failed to delete the open transaction with ID {open_transaction_duplicate.get('id')}.", state="error")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to add a new transaction", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    remove_duplicate_transactions(
        # start_date="2023-05-04",
        # end_date="2023-05-04",
    )