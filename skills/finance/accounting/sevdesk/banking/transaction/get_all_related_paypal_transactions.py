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
from typing import List, Dict, Tuple
from datetime import timedelta
from dateutil.parser import parse
from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions
from datetime import datetime


def get_all_related_paypal_transactions(transaction: dict, is_expense: bool = True) -> Tuple[List[Dict], Dict]:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Getting all related PayPal transactions ...")
        # Convert the entryDate string to a datetime object
        entry_date = parse(transaction.get("entryDate"))

        # search for all transactions with the same amount and a date +- 14 days from the original transaction, in the paypal account
        related_paypal_transactions_with_real_ammount = get_transactions(
            bank_account="PayPal",
            amount=transaction.get("amount"),
            start_date=entry_date - timedelta(days=14),
            end_date=entry_date + timedelta(days=14),
            is_open=True
        )

        related_bank_account_transactions_with_negative_ammount = get_transactions(
            bank_account="PayPal",
            amount=str(float(transaction.get("amount")) * -1),
            start_date=entry_date - timedelta(days=14),
            end_date=entry_date + timedelta(days=14),
            is_open=True
        )

        related_bank_account_transactions = get_transactions(
            exclude_bank_account="PayPal",
            amount=transaction.get("amount"),
            start_date=entry_date - timedelta(days=14),
            end_date=entry_date + timedelta(days=14),
            is_open=True
        )


        # add them all together to all_transactions
        all_transactions = related_paypal_transactions_with_real_ammount + related_bank_account_transactions_with_negative_ammount + related_bank_account_transactions

        # make sure no transaction is added twice (based on ID)
        # Create a set to store unique ids
        unique_ids = set()

        # Filter out duplicates
        all_transactions = [x for x in all_transactions if x.get("id") not in unique_ids and not unique_ids.add(x.get("id"))]

        if not all_transactions:
            add_to_log("No related transactions found. Asking user to manually process transaction.", module_name="SevDesk", state="error")
            return [None, None]

        # check if the total amount of all transactions is equal to the original transaction amount
        total_amount = 0
        for processing_transaction in all_transactions:
            total_amount += float(processing_transaction.get("amount"))

        if total_amount != float(transaction.get("amount")) and total_amount != float(transaction.get("amount")) * -1:
            add_to_log("The total amount of all transactions is not equal to the original transaction amount. It seems some of the transactions are not actually related. Asking user to manually process transaction.", module_name="SevDesk", state="error")
            return [None, None]

        # define primary_transaction: it is an expense (-amount), it does not have "paypal" in the payeePayerName
        primary_transaction = transaction
        if is_expense:
            for processing_transaction in all_transactions:
                if float(processing_transaction.get("amount")) < 0 and "paypal" not in processing_transaction.get("payeePayerName").lower():
                    primary_transaction = processing_transaction
                    break
        
        # add the payeePayerName to the paymtPurpose if it is not already in there
        primary_transaction["payment_purpose"] = primary_transaction["paymtPurpose"]
        if "payeePayerName" in primary_transaction and primary_transaction["payeePayerName"] and "paymtPurpose" in primary_transaction and primary_transaction["paymtPurpose"] and not " - " in primary_transaction["paymtPurpose"]:
            primary_transaction["paymtPurpose"] = primary_transaction["payeePayerName"]+ " - " + primary_transaction["paymtPurpose"]

        # add primary_transaction["date_readable"],primary_transaction["bank_account"]
        primary_transaction["date_readable"] = datetime.strptime(primary_transaction["valueDate"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y/%m/%d %H:%M:%S")
        primary_transaction["bank_account"] = "PayPal"
        
        # sort the transactions in all_transactions, first all the positive ones, then the negative ones (if expense), else the other way around
        if is_expense:
            all_transactions.sort(key=lambda x: float(x.get("amount")), reverse=True)

        return [all_transactions, primary_transaction]

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get all related PayPal transactions", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    all_transactions, primary_transaction = get_all_related_paypal_transactions(transaction={
        "entryDate": "2023-08-05T13:27:14+02:00",
        "amount": "-10.34",
        "paymtPurpose": "PayPal - Paypal *fugendichtb",
        "checkAccount": {
            "id": "5566672",
            "objectName": "CheckAccount"
        }
    })
    print(all_transactions)
    print(primary_transaction)