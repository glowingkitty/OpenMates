################

# Default Imports

################
import sys
import os
import re
import json
from datetime import datetime, timezone

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################
import calendar


def get_transactions(
    payment_purpose: str = None,
    payment_purpose_contains: str = None,
    payment_purpose_exclude: str = None,
    exact_time: str = None,
    start_date: str = None,
    end_date: str = None,
    payee_payer_name: str = None,
    amount: float = None,
    amount_min: float = None,
    amount_max: float = None,
    original_currency: str = None,
    original_currency_amount: float = None,
    original_currency_amount_min: float = None,
    original_currency_amount_max: float = None,
    calculate_total_value: bool = False,
    save_to_json: bool = False
) -> list:
    try:
        add_to_log(module_name="Banks", color="blue", state="start")
        add_to_log("Searching for transactions ...")

        # Load transactions from the JSON file
        filepath = f"{main_directory}temp_data/finance/bank_transactions.json"
        with open(filepath, 'r') as file:
            transactions = json.load(file)

        # Filter transactions
        if payment_purpose != None:
            add_to_log(f"Filtering transactions for payment purpose: {payment_purpose}")
            # check if any of the legs has a description that matches the payment purpose
            filtered_transactions = [transaction for transaction in transactions if any([leg.get("description").lower() == payment_purpose.lower() for leg in transaction.get("legs")])]

            # also check if the transaction reference matches the payment purpose
            filtered_transactions += [transaction for transaction in transactions if transaction.get("reference", "").lower() == payment_purpose.lower()]

            # if no transactions were found and the payment purpose contains " - ", try to split the payment purpose and search for the second part
            if len(filtered_transactions) == 0 and " - " in payment_purpose:
                payment_purpose = " - ".join(payment_purpose.split(" - ")[1:])
                add_to_log(f"Filtering transactions for payment purpose: {payment_purpose}")
                # check if any of the legs has a description that matches the payment purpose
                filtered_transactions = [transaction for transaction in transactions if any([leg.get("description").lower() == payment_purpose.lower() for leg in transaction.get("legs")])]
                # also check if the transaction reference matches the payment purpose
                filtered_transactions += [transaction for transaction in transactions if transaction.get("reference", "").lower() == payment_purpose.lower()]

            transactions = filtered_transactions

        if payment_purpose_contains != None:
            add_to_log(f"Filtering transactions for payment purpose containing: {payment_purpose_contains}")
            # check if any of the legs has a description that contains the payment purpose
            transactions = [transaction for transaction in transactions if any([payment_purpose_contains.lower() in leg.get("description").lower() for leg in transaction.get("legs")])]

        if payment_purpose_exclude != None:
            add_to_log(f"Filtering transactions for payment purpose excluding: {payment_purpose_exclude}")
            # check if any of the legs has a description that contains the payment purpose
            transactions = [transaction for transaction in transactions if not any([payment_purpose_exclude.lower() in leg.get("description").lower() for leg in transaction.get("legs")])]

        if exact_time != None:
            # if the exact time contains timezone (2024-01-03T12:35:06+01:00 for example), first convert it to UTC
            try:
                exact_time = datetime.strptime(exact_time, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                try:
                    exact_time = datetime.strptime(exact_time, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    pass
            add_to_log(f"Filtering transactions for exact time: {exact_time}")

            # check if the transaction date is equal to the exact time (but ignore the milliseconds)
            transactions = [transaction for transaction in transactions if transaction.get("created_at")[:-7] == exact_time[:-7]]

        if start_date != None:
            add_to_log(f"Filtering transactions for transactions after: {start_date}")
            # check if the transaction date (example: 2023-05-19T17:11:53.811472Z) is after the start date (example: 2023-05-19), by parsing all dates correctly and comparing them
            start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # parse the dates from all transactions and compare them datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc,microsecond=0)
            transactions = [transaction for transaction in transactions if datetime.strptime(transaction.get("created_at"), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc,microsecond=0) >= start_date]
            
        if end_date != None:
            add_to_log(f"Filtering transactions for transactions before: {end_date}")
            # check if the transaction date (example: 2023-05-19T17:11:53.811472Z) is before the end date (example: 2023-05-19), by parsing all dates correctly and comparing them
            try:
                end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59,tzinfo=timezone.utc)
            except ValueError:
                year, month = map(int, end_date.split('-')[:2])
                last_day = calendar.monthrange(year, month)[1]
                end_date = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
            # parse the dates from all transactions and compare them datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc,microsecond=0)
            transactions = [transaction for transaction in transactions if datetime.strptime(transaction.get("created_at"), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc,microsecond=0) <= end_date]

        if payee_payer_name != None:
            add_to_log(f"Filtering transactions for payee/payer name: {payee_payer_name}")
            # check if "merchant_name" or any leg "description" contains the payee/payer name
            transactions = [transaction for transaction in transactions if transaction.get("merchant_name") and payee_payer_name.lower() in transaction.get("merchant_name").lower() or any([payee_payer_name.lower() in leg.get("description").lower() for leg in transaction.get("legs")])]

        if amount != None:
            add_to_log(f"Filtering transactions for amount: {amount}")
            # check if the amount in any of the legs is equal to the amount
            transactions = [transaction for transaction in transactions if any([float(leg.get("amount")) == float(amount) for leg in transaction.get("legs")])]

        if amount_min != None:
            add_to_log(f"Filtering transactions for amount >= {amount_min}")
            # check if the amount in any of the legs is equal to the amount
            transactions = [transaction for transaction in transactions if any([float(leg.get("amount")) >= float(amount_min) for leg in transaction.get("legs")])]

        if amount_max != None:
            add_to_log(f"Filtering transactions for amount <= {amount_max}")
            # check if the amount in any of the legs is equal to the amount
            transactions = [transaction for transaction in transactions if any([float(leg.get("amount")) <= float(amount_max) for leg in transaction.get("legs")])]

        if original_currency != None:
            add_to_log(f"Filtering transactions for original currency: {original_currency}")
            # check if the original currency in any of the legs is equal to the original currency
            transactions = [transaction for transaction in transactions if any([leg.get("bill_currency") == original_currency for leg in transaction.get("legs")])]

        if original_currency_amount != None:
            add_to_log(f"Filtering transactions for original currency amount: {original_currency_amount}")
            # check if the original currency amount in any of the legs is equal to the original currency amount
            transactions = [transaction for transaction in transactions if any([float(leg.get("bill_amount")) == float(original_currency_amount) for leg in transaction.get("legs")])]

        if original_currency_amount_min != None:
            add_to_log(f"Filtering transactions for original currency amount >= {original_currency_amount_min}")
            # check if the original currency amount in any of the legs is equal to the original currency amount
            transactions = [transaction for transaction in transactions if any([float(leg.get("bill_amount")) >= float(original_currency_amount_min) for leg in transaction.get("legs")])]

        if original_currency_amount_max != None:
            add_to_log(f"Filtering transactions for original currency amount <= {original_currency_amount_max}")
            # check if the original currency amount in any of the legs is equal to the original currency amount
            transactions = [transaction for transaction in transactions if any([float(leg.get("bill_amount")) <= float(original_currency_amount_max) for leg in transaction.get("legs")])]


        add_to_log(f"Found {len(transactions)} transactions matching the criteria.", state="success")

        if calculate_total_value:
            total_value = 0
            for transaction in transactions:
                for leg in transaction.get("legs"):
                    total_value += leg.get("amount")
                    if leg.get("fee"):
                        total_value -= leg.get("fee")
            total_value = round(total_value, 2)
            add_to_log(f"Total value of all transactions: {total_value}", state="success")
        
        if save_to_json:
            filepath = f"{main_directory}temp_data/finance/filtered_bank_transactions.json"
            with open(filepath, 'w') as file:
                json.dump(transactions, file, indent=4)
            add_to_log(f"Successfully saved {len(transactions)} transactions to {filepath}", state="success")

        return transactions

    except Exception as e:
        process_error(f"Failed to search transactions: {e}", traceback=traceback.format_exc())
        return []

# Example test
if __name__ == "__main__":
    get_transactions(
        start_date="2024-01-02",
        end_date="2024-01-02",
        amount=-12.9
    )
    # get_transactions(payment_purpose="Freelancer Pro plan fee", calculate_total_value=True)