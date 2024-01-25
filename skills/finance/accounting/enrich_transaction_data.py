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
from skills.intelligence.load_systemprompt import load_systemprompt
from skills.intelligence.ask_llm import ask_llm
from skills.finance.accounting.sevdesk.banking.check_account.get_check_accounts import get_check_accounts
from skills.finance.banks.get_transactions import get_transactions
import asyncio
import hashlib
import json


def enrich_transaction_data(transaction: dict) -> dict:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Adding additional data to transaction ...")

        bank_accounts = get_check_accounts()

        # add additional temp data to transaction
        if transaction.get("payeePayerName"):
            transaction["payment_purpose"] = transaction["paymtPurpose"].split(' - ')[1] if ' - ' in transaction["paymtPurpose"] else transaction["paymtPurpose"]
        else:
            transaction["payment_purpose"] = transaction["paymtPurpose"]
        transaction["date_readable"] = datetime.strptime(transaction["valueDate"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y/%m/%d %H:%M:%S")
        for bank_account in bank_accounts:
            if bank_account["id"] == transaction["checkAccount"]["id"]:
                transaction["bank_account"] = bank_account["name"]
                break

        bank_transaction = get_transactions(
            amount=transaction["amount"], 
            exact_time=transaction["entryDate"],
            payment_purpose=transaction["paymtPurpose"]
        )
        if len(bank_transaction) == 0:
            add_to_log(f"Failed to process transaction. No bank transaction found for transaction {transaction['id']}.", module_name="Finance", state="error")
            return None
        elif len(bank_transaction) == 1:
            bank_transaction = bank_transaction[0]
            if 'id' not in bank_transaction:
                add_to_log("No id found in bank transaction. Therefore creating unique id based on whole dict.", module_name="Finance")
                bank_transaction_json = json.dumps(bank_transaction, sort_keys=True)
                bank_transaction['id'] = hashlib.sha256(bank_transaction_json.encode()).hexdigest()
            add_to_log(f"Found bank transaction {bank_transaction['id']} for transaction {transaction['id']}.", module_name="Finance")

            if "bill_amount" in bank_transaction["legs"][0] and bank_transaction["legs"][0]["bill_amount"] is not None:
                transaction["bill_amount"] = bank_transaction["legs"][0]["bill_amount"]

            if "bill_currency" in bank_transaction["legs"][0] and bank_transaction["legs"][0]["bill_currency"] is not None:
                transaction["bill_currency"] = bank_transaction["legs"][0]["bill_currency"]
            
            # if the transaction is a paypal transaction, mark it
            if "paypal " in bank_transaction["legs"][0]["description"].lower() or " paypal-" in bank_transaction["legs"][0]["description"].lower():
                transaction["is_paypal_transaction"] = True
            else:
                transaction["is_paypal_transaction"] = False


            # add keywords to transaction based on LLM response
            systemprompt_extract_keywords = load_systemprompt(special_usecase="bank_transactions_processing/extract_keywords_to_find_matching_voucher_from_transaction_purpose")
            message_history = [
                        {"role": "system", "content":systemprompt_extract_keywords},
                        {"role": "user", "content":transaction["paymtPurpose"]}
                        ]
        
            keywords_list_json = asyncio.run(ask_llm(
                bot={
                    "user_name": "finn", 
                    "system_prompt": systemprompt_extract_keywords, 
                    "creativity": 0, 
                    "model": "gpt-4"
                },
                message_history=message_history,
                response_format="json"
            )
            )

            # add keywords to transaction
            transaction["keywords"] = keywords_list_json["keywords"] if keywords_list_json and 'keywords' in keywords_list_json else transaction["paymtPurpose"].split(' - ')

            add_to_log(f"Successfully enriched transaction data for transaction {transaction['id']}", state="success")
            return transaction
        else:
            add_to_log(f"Failed to process transaction. Multiple bank transactions found for transaction {transaction['id']}.", module_name="Finance", state="error")
            return None

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to enrich transaction data", traceback=traceback.format_exc())
        return None#