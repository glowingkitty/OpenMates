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

from datetime import datetime
from skills.finance.accounting.sevdesk.banking.check_account.get_check_accounts import get_check_accounts
from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions

def check_if_merchant_sends_invoice_emails(transaction: dict) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Checking if merchant generally sends invoice emails ...")

        profile_details = load_profile_details()
        
        # search in email inbox (if merchant not on list of merchants who never send invoices via email)
        # check if any of the merchants is in the payeePayerName (either as a full match or as a "{name} " or " {name}" match). Check for case insensitive matches
        merchant_exact_match_options = []
        merchant_partial_match_options = []
        for merchant in profile_details["merchants_who_never_send_invoice_emails"]:
            merchant_exact_match_options.append(merchant)
            merchant_partial_match_options.append(f"{merchant} ")
            merchant_partial_match_options.append(f" {merchant}")

        merchant_sends_invoice_emails = True
        for merchant in merchant_exact_match_options:
            if "payeePayerName" in transaction and transaction["payeePayerName"] and merchant.lower() == transaction["payeePayerName"].lower():
                add_to_log(f"Merchant '{merchant}' is known to never send email invoices. Skipping search in emails ...")
                merchant_sends_invoice_emails = False
                break

        if merchant_sends_invoice_emails:
            for merchant in merchant_partial_match_options:
                if "payeePayerName" in transaction and transaction["payeePayerName"] and merchant.lower() in transaction["payeePayerName"].lower():
                    add_to_log(f"Merchant '{merchant}' is known to never send email invoices. Skipping search in emails ...")
                    merchant_sends_invoice_emails = False
                    break

        add_to_log("Successfully checked if merchant generally sends invoice emails", state="success")
        return merchant_sends_invoice_emails

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to check if merchant generally sends invoice emails", traceback=traceback.format_exc())
        return None