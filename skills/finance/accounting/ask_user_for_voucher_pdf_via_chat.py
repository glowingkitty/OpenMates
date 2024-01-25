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

from chat.mattermost.functions.message.send_message import send_message
from skills.finance.accounting.get_user_already_asked_for_manual_processing import get_user_already_asked_for_manual_processing
from skills.finance.accounting.save_user_asked_for_manual_processing import save_user_asked_for_manual_processing

def ask_user_for_voucher_pdf_via_chat(transaction: dict) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Asking user via chat to manually upload voucher PDF into accounting system ...")

        profile_details = load_profile_details()

        # check if the notification was already sent
        if get_user_already_asked_for_manual_processing(transaction=transaction):
            add_to_log("User was already asked via chat to manually upload voucher PDF into accounting system")
            return True
    
        # send a first message, then based on the returnd message ID, send a second message with the table attached to it
        initial_message_id = send_message(
            (
                "❌ Sorry, I couldn't find the invoice / receipt for the transaction anywhere. "
                "Could you please [add it yourself to SevDesk?](https://my.sevdesk.de/ex/VOU) Thanks! :slightly_smiling_face:\n\n"
                "| Date/Time | {transaction[date_readable]} |\n"
                "| ---------------- | ---------------- |\n"
                "| Bank account | {transaction[bank_account]} |\n"
                "| Amount | {transaction[amount]} EUR |\n"
                "{amount_bill_row}"
                "{payee_payer_row}"
                "| Payment purpose | {transaction[payment_purpose]} |\n"
            ).format(
                transaction=transaction,
                amount_bill_row="| Amount (bill) | {transaction[bill_amount]} {transaction[bill_currency]} |\n".format(transaction=transaction) if 'bill_amount' in transaction and transaction['bill_amount'] else "",
                payee_payer_row="| Payee/Payer | {transaction[payeePayerName]} |\n".format(transaction=transaction) if 'payeePayerName' in transaction and transaction['payeePayerName'] else ""
            ),
            bot_name="finn",
            channel_name="accounting"
        )

        # send a second message with the table attached to it
        send_message(
            f"@{profile_details['accounting_responsible_person']['chat_username']}",
            bot_name="finn",
            channel_name="accounting",
            thread_id=initial_message_id
        )
        
        # save that the user was asked to manually upload the voucher PDF (to avoid asking again)
        save_user_asked_for_manual_processing(transaction=transaction)

        add_to_log("Successfully asked user via chat to manually upload voucher PDF into accounting system")
        return True

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to ask user via chat for voucher PDF", traceback=traceback.format_exc())
        return False