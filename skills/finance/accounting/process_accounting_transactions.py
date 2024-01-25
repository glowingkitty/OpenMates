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

from datetime import datetime, timezone, timedelta
from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions
from skills.finance.accounting.process_transaction import process_transaction
from skills.finance.accounting.ask_user_for_voucher_pdf_via_chat import ask_user_for_voucher_pdf_via_chat
from skills.cloud_storage.dropbox.search_files import search_files
from skills.finance.accounting.enrich_transaction_data import enrich_transaction_data
from skills.finance.accounting.get_user_already_asked_for_manual_processing import get_user_already_asked_for_manual_processing
import time
from dateutil.relativedelta import relativedelta
import calendar


def process_accounting_transactions(
        start_month: str = None,
        end_month: str = None,
        process_last_days: int = None,
        temp_files_path: str = f"{main_directory}temp_data/cloud_storage/voucher_pdfs"
        ):
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Processing all accounting transactions ...")

        ###############################################
        ### Download all vouchers from cloud storage ##
        ### so they can be efficiently searched #######
        ###############################################

        # create folder if it does not exist
        os.makedirs(temp_files_path, exist_ok=True)
        # download all voucher PDFs from Dropbox
        search_files(path="/Documents/Finance/Vouchers",query=".pdf",get_all=True,download=True,download_path=temp_files_path)


        # Parse the start and end dates
        if start_month and end_month:
            start_date = datetime.strptime(start_month, "%Y-%m")
            end_date = datetime.strptime(end_month, "%Y-%m") + relativedelta(months=+1, days=-1)
        elif process_last_days:
            end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = (end_date - timedelta(days=process_last_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            raise ValueError("Invalid date parameters")
        
        add_to_log(f"start_date: {start_date}", module_name="Finance")
        add_to_log(f"end_date: {end_date}", module_name="Finance")


        # Get all months in the range
        months = [start_date + relativedelta(months=+i) for i in range((end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1)]
        add_to_log(f"Processing transactions for the following months: {', '.join(month.strftime('%Y-%m') for month in months)}.", module_name="Finance")


        for month in months:
            add_to_log(f"Processing transactions for month {month.strftime('%Y-%m')} ...", module_name="Finance")

            # Get the start and end date of the month
            # if the start_date month is equal to this month, use the start_date as start_date
            if start_date.month == month.month:
                this_month_start_date = start_date
            else:
                this_month_start_date = month.replace(day=1)
            
            # if the end_date month is equal to this month, use the end_date as end_date, else use the last day of the month using calendar
            if end_date.month == month.month:
                this_month_end_date = end_date
            else:
                this_month_end_date = month.replace(day=calendar.monthrange(month.year, month.month)[1])

            add_to_log(f"with start_date: {this_month_start_date}", module_name="Finance")
            add_to_log(f"and end_date: {this_month_end_date}", module_name="Finance")

            while True:

                transactions = get_transactions(is_open=True, start_date=this_month_start_date, end_date=this_month_end_date)
                
                paypal_transaction_found = False

                ###############################################
                ##### Process all accounting transactions #####
                ###############################################
                
                add_to_log(f"Processing {len(transactions)} transactions ...", module_name="Finance")
                time.sleep(4)
                for transaction in transactions:
                    success = False
                    # check if the transaction is on the list of "user was asked to manually process this transaction", if so, skip the transaction
                    if get_user_already_asked_for_manual_processing(transaction):
                        continue
                        

                    # adding more temp details to transaction
                    transaction = enrich_transaction_data(transaction)

                    if transaction:
                        days_age = (datetime.now(timezone.utc) - datetime.strptime(transaction["valueDate"], "%Y-%m-%dT%H:%M:%S%z")).days
                        
                        
                        if float(transaction["amount"]) > 0:
                            add_to_log(f"Transaction {transaction['id']} (income) from {transaction['valueDate']} is {days_age} days old.", module_name="Finance")
                        elif float(transaction["amount"]) < 0:
                            add_to_log(f"Transaction {transaction['id']} (expense) from {transaction['valueDate']} is {days_age} days old", module_name="Finance")

                        # process (with amount, currency, date, description, sender, receiver, original amount, original currency)
                        success = process_transaction(transaction, local_folder_path=temp_files_path+"/Documents/Finance/Vouchers")

                        if not success:
                            if days_age >= 7:
                                add_to_log(f"Failed to process transaction {transaction['id']}. Transaction is older then 7 days.", module_name="Finance", state="error")
                                ask_user_for_voucher_pdf_via_chat(transaction)
                            else:
                                add_to_log(f"Failing to process transaction {transaction['id']}. Transaction is younger then 7 days. Will try again tomorrow.", module_name="Finance", state="error")

                    # if the transaction was a paypal transaction, reload the transactions to make sure the already booked paypal transactions are not attempted to be booked again
                    if transaction and transaction.get("is_paypal_transaction") == True and success == True:
                        add_to_log("Reloading transactions to make sure the already booked paypal transactions are not attempted to be booked again ...", module_name="Finance")
                        paypal_transaction_found = True
                        break
                        
                
                if not paypal_transaction_found:
                    break
                            

        add_to_log("Successfully processed all accounting transactions", module_name="Finance", state="success")

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to process accounting transactions", traceback=traceback.format_exc())


if __name__ == "__main__":
    temp_files_path = "/Users/kitty/Library/CloudStorage/Dropbox"
    process_accounting_transactions(temp_files_path=temp_files_path, start_month="2023-12", end_month="2023-12")