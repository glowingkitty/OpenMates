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

from skills.finance.accounting.sevdesk.banking.check_account.get_check_accounts import get_check_accounts
import json
from dateutil.parser import parse
from dateutil.tz import tzutc
from calendar import monthrange


def get_transactions(
        bank_account: str = None,               # Name of the bank account
        exclude_bank_account: str = None,       # Name of the bank account
        is_open: bool = None,                   # If true, only open transactions are returned, if false, only booked transactions are returned
        payment_purpose: str = None,            # the purpose of the transaction
        payment_purpose_contains: str = None,   # the purpose of the transaction
        start_date: str = None,                 # example YYYY-MM-DD or MM/YYYY, the start date to search for transactions
        end_date: str = None,                   # example YYYY-MM-DD or MM/YYYY, the end date to search for transactions
        payee_payer_name: str = None,           # Name of the payee/payer
        amount: float = None,                   # Amount of the transaction
        amount_min: float = None,               # Minimum amount of the transaction
        amount_max: float = None,               # Maximum amount of the transaction
        only_credit: bool = None,               # If true, only credit transactions are returned
        only_debit: bool = None,                # If true, only debit transactions are returned
    ) -> list:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Getting transactions ...")

        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")

        # Define the API endpoint
        api_endpoint = "https://my.sevdesk.de/api/v1/CheckAccountTransaction"

        headers = {
            "Authorization": api_key
        }

        # make sure start_date and end_date are in the correct format
        if start_date is not None:
            start_date = str(start_date)
        
        if end_date is not None:
            end_date = str(end_date)

        # fint the check account id based on the bank account name
        check_account_id = None
        if bank_account:
            check_accounts = get_check_accounts()
            for check_account in check_accounts:
                if check_account.get("name") == bank_account:
                    check_account_id = check_account.get("id")
                    break
        
        # get the ID of exclude_bank_account
        exclude_bank_account_id = None
        if exclude_bank_account:
            check_accounts = get_check_accounts()
            for check_account in check_accounts:
                if check_account.get("name") == exclude_bank_account:
                    exclude_bank_account_id = check_account.get("id")
                    break

        # Prepare the request payload
        transaction_data = {
            "limit": 10000
        }

        if check_account_id:
            transaction_data["checkAccount"] = {
                "id": check_account_id,
                "objectName": "CheckAccount"
            }

        if payment_purpose is not None:
            transaction_data["paymtPurpose"] = payment_purpose
        
        if payee_payer_name is not None:
            transaction_data["payeePayerName"] = payee_payer_name
        
        if only_credit is not None:
            transaction_data["onlyCredit"] = only_credit

        if only_debit is not None:
            transaction_data["onlyDebit"] = only_debit

        # Make the GET request
        response = requests.get(api_endpoint, json=transaction_data, headers=headers)

        # Check for successful response
        if response.status_code == 200:
            results = response.json().get("objects")

            # if exclude_bank_account is set, filter out all transactions with that bank account
            if exclude_bank_account is not None:
                results = [result for result in results if result.get("checkAccount").get("id") != exclude_bank_account_id]

            if payment_purpose_contains is not None:
                results = [result for result in results if payment_purpose_contains.lower() in result.get("paymtPurpose").lower()]

            # filter further
            if amount is not None:
                results = [result for result in results if float(result.get("amount")) == float(amount)]

            if amount_min is not None:
                results = [result for result in results if float(result.get("amount")) >= float(amount_min)]

            if amount_max is not None:
                results = [result for result in results if float(result.get("amount")) <= float(amount_max)]
            
            if start_date is not None:

                # try to parse as MM/YYYY
                if "/" in start_date:
                    start_date = parse("01/"+start_date).replace(tzinfo=tzutc())

                # try to parse other formats
                else:
                    start_date = parse(start_date)
                    if start_date.tzinfo is None or start_date.tzinfo.utcoffset(start_date) is None:
                        start_date = start_date.replace(tzinfo=tzutc())
                    else:
                        start_date = start_date.astimezone(tzutc())

                start_date = start_date.replace(microsecond=0)
                add_to_log(f"Filtering for start_date: {start_date}")

                # filter results, by making sure "entryDate" is >= start_date
                filtered_results = []
                for result in results:
                    entry_date = parse(result.get("entryDate"))
                    value_date = parse(result.get("valueDate")) if result.get("valueDate") else None

                    if entry_date.tzinfo is None or entry_date.tzinfo.utcoffset(entry_date) is None:
                        entry_date = entry_date.replace(tzinfo=tzutc())
                    else:
                        entry_date = entry_date.astimezone(tzutc())

                    if value_date:
                        if value_date.tzinfo is None or value_date.tzinfo.utcoffset(value_date) is None:
                            value_date = value_date.replace(tzinfo=tzutc())
                        else:
                            value_date = value_date.astimezone(tzutc())

                    entry_date = entry_date.replace(microsecond=0)
                    value_date = value_date.replace(microsecond=0) if value_date else None

                    if (value_date and value_date.replace(tzinfo=tzutc()) >= start_date.replace(tzinfo=tzutc())) or entry_date.replace(tzinfo=tzutc()) >= start_date.replace(tzinfo=tzutc()):
                        filtered_results.append(result)

                results = filtered_results


            if end_date is not None:

                # try to parse as MM/YYYY
                if "/" in end_date:
                    end_date = parse("01/"+end_date).replace(tzinfo=tzutc())

                    # set to the last day of the month
                    end_date = end_date.replace(day=monthrange(end_date.year, end_date.month)[1], hour=23, minute=59, second=59)

                # try to parse other formats
                else:
                    end_date = parse(end_date)
                    if end_date.tzinfo is None or end_date.tzinfo.utcoffset(end_date) is None:
                        end_date = end_date.replace(tzinfo=tzutc())
                    else:
                        end_date = end_date.astimezone(tzutc())

                    # if the time is 00:00:00, set it to 23:59:59
                    if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
                        end_date = end_date.replace(hour=23, minute=59, second=59)

                end_date = end_date.replace(microsecond=0)
                add_to_log(f"Filtering for end_date: {end_date}")

                # filter results, by making sure "entryDate" is <= end_date
                filtered_results = []
                for result in results:
                    entry_date = parse(result.get("entryDate"))
                    value_date = parse(result.get("valueDate")) if result.get("valueDate") else None

                    if entry_date.tzinfo is None or entry_date.tzinfo.utcoffset(entry_date) is None:
                        entry_date = entry_date.replace(tzinfo=tzutc())
                    else:
                        entry_date = entry_date.astimezone(tzutc())

                    if value_date:
                        if value_date.tzinfo is None or value_date.tzinfo.utcoffset(value_date) is None:
                            value_date = value_date.replace(tzinfo=tzutc())
                        else:
                            value_date = value_date.astimezone(tzutc())

                    entry_date = entry_date.replace(microsecond=0)
                    value_date = value_date.replace(microsecond=0) if value_date else None

                    if (value_date and value_date.replace(tzinfo=tzutc()) <= end_date.replace(tzinfo=tzutc())) or entry_date.replace(tzinfo=tzutc()) <= end_date.replace(tzinfo=tzutc()):
                        filtered_results.append(result)

                results = filtered_results


            if is_open is not None:
                if is_open == True:
                    results = [result for result in results if result.get("status") == "100"]
                elif is_open == False:
                    results = [result for result in results if result.get("status") == "400"]

            if len(results) > 0:
                add_to_log(f"Successfully got {len(results)} transactions", state="success")
                return results

            else:
                add_to_log(f"No transactions found", state="success")
                return []
            
        else:
            process_error(f"Failed to get transactions. Status code: {response.status_code}, Response: {response.text}")


    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to add a new transaction", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    import subprocess
    transactions = get_transactions(
        # is_open=True,
        # start_date="04/2023",
        # end_date="09/2023",
        start_date="2023-03-31",
        end_date="2023-03-31",
        # start_date="2023-10-08T09:57:12.120175Z",
        # end_date="2023-10-08T09:57:12.120175Z",
        # amount=-0.59,
        # bank_account="Finom",
    )
    # print(transactions)
    # save as json file
    folder_path = f"{main_directory}temp_data/finance/sevdesk"
    file_path = f"{folder_path}/transactions.json"
    os.makedirs(folder_path, exist_ok=True)
    with open(file_path, 'w') as outfile:
        json.dump(transactions, outfile, indent=4)
    
    subprocess.run(["code", file_path])