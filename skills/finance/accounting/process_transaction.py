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

from skills.finance.accounting.sevdesk.voucher.add_voucher import add_voucher
from skills.finance.accounting.sevdesk.banking.transaction.get_all_related_paypal_transactions import get_all_related_paypal_transactions
from skills.finance.accounting.search_voucher_in_emails import search_voucher_in_emails
from skills.finance.accounting.search_vouchers_locally import search_vouchers_locally
from skills.finance.accounting.check_if_merchant_sends_invoice_emails import check_if_merchant_sends_invoice_emails
from skills.finance.accounting.move_or_upload_voucher_to_correct_cloud_storage_folder import move_or_upload_voucher_to_correct_cloud_storage_folder
from chat.mattermost.functions.message.send_message import send_message


def process_transaction(transaction: dict, local_folder_path: str) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Processing transaction ...")

        profile_details = load_profile_details()
        all_transactions = [transaction]

        if "is_paypal_transaction" in transaction and transaction["is_paypal_transaction"] == True:
            add_to_log(
                (
                    "Transaction is a paypal transaction. Getting all related transations to this PayPal transaction "
                    "(value added to PayPal account, value removed from PayPal account, value removed from bank account) ..."
                )
            )
            all_transactions, primary_transaction = get_all_related_paypal_transactions(transaction)

            # set the transaction to the primary transaction (which also includes the correct payee/payer name, instead of "PayPal")
            transaction = primary_transaction

        # search in cloud storage (locally stored for efficiency reasons) for pdf via ocr (date, amount), also process dropbox file with ocr if not yet done
        add_to_log("Searching in cloud storage for matching vouchers...")
        voucher_filepath_local, voucher_filepath_cloud = search_vouchers_locally(transaction, folder_path=local_folder_path)

        if not voucher_filepath_local and check_if_merchant_sends_invoice_emails(transaction) == True:
            add_to_log("No matching voucher found in cloud storage. Searching in emails...")
            voucher_filepath_local, voucher_filepath_cloud = search_voucher_in_emails(transaction)

        if voucher_filepath_local:
            add_to_log("Successfully processed transaction. Found one matching voucher.", module_name="Finance", state="success")
            add_to_log(f"For the transaction: '{transaction}' ...'")
            add_to_log(f"Found voucher: '{voucher_filepath_local}' ...'")

            add_to_log("Processing the voucher now and adding to accounting ...")
            # process with bookkeeping software
            add_to_log(f"Processing the file: '{voucher_filepath_local}' ...'")
            add_to_log(f"For the transaction: '{transaction}' ...'")
            voucher_data = add_voucher(
                voucher_filepath_local,
                transactions=all_transactions,
                primary_transaction=transaction,
                cloud_sync_path=voucher_filepath_cloud
                )
            if not voucher_data:
                add_to_log("Failed to process voucher", state="error")
                return False

            # once processed, also move the file to the correct folder in cloud storage
            voucher_filepath_cloud = move_or_upload_voucher_to_correct_cloud_storage_folder(
                voucher_data=voucher_data, 
                voucher_filepath_local=voucher_filepath_local,
                voucher_filepath_cloud=voucher_filepath_cloud
                )

            if voucher_filepath_cloud and voucher_data.get("voucher") and voucher_data["voucher"].get("id"):
                add_to_log("Successfully added the voucher. Sending a notification to the user now to ask to double check the extracted voucher data ...")
                all_transactions_message = ""

                for transaction in all_transactions:
                    transaction_message = (
                        "\n"
                        "| Date/Time | {date_readable} |\n"
                        "| ---------------- | ---------------- |\n"
                        "| Bank account | {bank_account} |\n"
                        "| Amount | {amount} EUR |\n"
                        "{amount_bill_row}"
                        "{payee_payer_row}"
                        "| Payment purpose | {payment_purpose} |\n"
                    ).format(
                        date_readable=transaction["date_readable"],
                        bank_account=transaction["bank_account"],
                        amount=transaction["amount"],
                        amount_bill_row="| Amount (bill) | {bill_amount} {bill_currency} |\n".format(**transaction) if 'bill_amount' in transaction else "",
                        payee_payer_row="| Payee/Payer | {payeePayerName} |\n".format(**transaction) if 'payeePayerName' in transaction else "",
                        payment_purpose=transaction["payment_purpose"]
                    )
                    all_transactions_message += transaction_message

                # Now you can send the entire message with all transactions
                initial_message_id = send_message(
                    (
                        f"✅ I just added a new invoice/receipt to SevDesk (and uploaded it [to Dropbox](https://www.dropbox.com/preview{voucher_filepath_cloud}) as well). Can you [double check HERE if all the data are correct](https://my.sevdesk.de/ex/detail/id/{voucher_data['voucher']['id']})? Thanks!\n"
                        "{all_transactions_message}"
                    ).format(
                        voucher_data=voucher_data,
                        all_transactions_message=all_transactions_message
                    ),
                    bot_name="finn",
                    channel_name="accounting"
                )
                
                send_message(
                    f"@{profile_details['accounting_responsible_person']['chat_username']}",
                    bot_name="finn",
                    channel_name="accounting",
                    thread_id=initial_message_id
                    )
            
                return True

        add_to_log(f"Failed to process transaction. No matching voucher found. ({transaction['entryDate']}, {transaction['paymtPurpose']}, {transaction['amount']})", module_name="Finance", state="error")
        return False

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to process transaction", traceback=traceback.format_exc())
        return False


if __name__ == "__main__":
    from skills.finance.accounting.enrich_transaction_data import enrich_transaction_data
    transaction = {
    }
    transaction = enrich_transaction_data(transaction)
    process_transaction(
        transaction=transaction,
        local_folder_path="/Users/kitty/Library/CloudStorage/Dropbox/Documents/Finance/Vouchers"
    )




# process:
# - if not on list of companies who never send invoice pdfs via email (exclude amazon for example):
#    - search in email inbox for invoice pdf (pdf files with "invoice" or "rechnung" in their name or if email subject contains "invoice" or "rechnung" and has a pdf file attached. If multiple pdf files attached, use ocr processing to find the right invoice file)
# - if no pdf found, search in dropbox for invoice pdf via ocr (date, amount)
#    - if multiple results found, use additional details and LLM and GPT4 vision to identify if any of them matches transaction
# - if no pdf found but email found with link to invoice (behind login), ask user to download invoice pdf and send it to chat for processing (for example for shopify)

# if pdf found:
# - process with LLLM and GPT4 vision (including ocr text for better accuracy) and send voucher to accounting
# - once voucher is added, search for related transactions (same amount, same date, both in positive and negative value (to include paypal transactions)) and link them to the voucher


# General learnings:
# - create a list of merchants known to send invoices via email and those who don't (not not check for pdfs for those who don't)
# - automatically update that list based on if invoices can be found via email
# - make sure that LEDs by glowingkitty is always replaced with Firstname Lastname
# - sometimes paypal payments can take easily 10 days after purchase, so better check for up to two weeks after purchase date for bank transactions and best auto check paypal transactions both 2 days, 7 days, and then every day after that up to 14 days after purchase date

# example scenarios:

# Scenario 1, paypal puchase:
# purchase at schraubenking.at with payment via paypal
# 15.12.2023 transaction of -11,57 EUR booked to paypal
# 15.12.2023 transaction of +11,57 EUR booked to paypal (to fill up paypal balance, will be booked from connected card/bank account)
# 19.12.2023 transaction of -11,57 EUR booked to bank account (paypal purchase)
# -> how to process this?

# Scenario 2, amazon purchase:
# -> auto split pdf file into seperate pdf invoices, since sometimes multiple invoices are in one pdf file (based on ocr for each page or gpt vision?)

# Scenario 3, JLCPCB purchase (Name: jlcpcb.com, Description: jlcpcb.com - jlcpcb.com)
# - JLCPCB invoices are available via web interface behind login, ask user to download invoice pdf and send it to chat for processing
# - special: invoice values are typically confusing and don't seem to match with actual booked amount (because of werid currency conversion?)
# - also annoying, JLCPCB has seperate invoice list for pcb orders / 3d printing orders and component orders
# - when processing vouchers, use (USD and EUR) value from transaction and not from invoice, but ideally also leave a note in the voucher that the invoice value was different (maybe tag?)
# - theoretically possible to automatically download invoice pdfs via web scraper, but not sure if worth the effort

# Scenario 4, OpenAI purchase:

# Scenario 5, Bauhaus purchase:

# Scenario 6, Amazon refund for returned items:
# -> search in emails for refund confirmation, print as pdf and process as new voucher file, as expense with negative value in the same category as the original purchase (search first for original voucher and then use same category)

# Scenario 7, Teleport purchase:
# - EVO FORGE SRL,CLUJ-NAPOCA is the name on the booking
# - search for invoices pdfs around the date of the booking in the email inbox, for each check if the value is in the pdf file text
# - if clear match, process voucher
# - else ask LLM for help? and if still no clear match found, ask user?

# Scenario 8, Google Domains:
# - sends no invoices, but emails with "Purchase receipt" in the subject
# - those emails have link to invoice pdf behind login. Maybe redirect that link to chat and ask user to download the pdf and send it to chat for processing?

# Scenario 9, Aliexpress:
# - no emails send (maybe an issue with my settings? maybe unsubscribe from all emails?)
# - invoices available via web interface behind login
# - ask user to download invoice pdf and send it to chat for processing
# - can be multiple invoices for single payment (same like with amazon)
# - try to auto extract value from invoice pdf. If match with transaction total, book them. Else inform user via chat and ask for help
# - processing idea: aliexpress is on list of merchants who has invoices behind login. Therefore user will be automatically asked two days after purchase to upload invoices for transaction into chat.
#     - then the pdfs will be automatically processed, the amount extracted. If the total amount doesn't match the transaction total, the user will be asked to help with the processing, else the user will be informed that the invoice was processed successfully

# Scenario 10, Hbholzmaus:
# - paid via paypal, means three transactions: one -value from paypal, one +value to paypal, one -value from bank account
# - if transaction on paypal, search for related transactions on bank account and connect them all to the voucher
# - invoice is send via PDF, can be processed automatically

# Scenario 11, Transfer between my accounts, for example added money to my Finom account (Name: REMOVED, Description: REMOVED - TeleportHQ fee)
# - if sender and receiver both me, directly ask via chat for pdf confirmation of transaction, to upload in chat
# - based on if transaction is minus (Privatentnahme) or positive (Privateneinlage), use those accounting types instead of trying to identify them from PDF

# Scenario 12, Shopify
# - doesn't send invoices via email but emails with "View bill" button
# - auto extract link from email and ask user to download invoice pdf and send it to chat for processing

# Scenario 13, Meetup.com (Name: meetup.com , Description: meetup.com - Meetup Org Sub 1m)
# - bill_currency is USD
# - therefore look for invoice in emails with value of bill_currency in the text
# - invoices are send via email as email, not pdf
# - email needs to be printed to pdf and then processed as voucher
# - if invoice found, set value to include amount (EUR) + fee and calculate the exchange rate based on the two values and link with transaction

# Scenario 14, Sumup (Name: SUMUP LIMITED, Description: SUMUP LIMITED - SUMUP PID281387 PAYOUT 250423)
# - for a purchase a customer made via sumup card payment terminal
# - need to manually download payout pdf from sumup dashboard and send it to chat for processing

# Scenario 15, customer pays via paypal (Name: 	Firstname Lastname, Description: rqLgIW4Y1eQt09sncYhfjwGBW / TXID 6VG57972GL802004D) 
# - paypal also charges fees (Description: Gebühren zu TXID 6VG57972GL802004D)
# - solution: book multiple transactions
#    - 1. paypal fees on paypal account (negative value, example: -6,04 EUR)
#    - 2. outgoing remaining amount on paypal account to bank account (negative value, example: -182,96 EUR) (if money transfered to bank account, else skip this step)
#    - 3. incoming remaining amount on bank account (positive value, example: +182,96 EUR) (if money transfered to bank account, else skip this step)
#    - 4. incoming amount on paypal account (positive value, example: +189,00 EUR)
# - change value of voucher / invoice to total value -  paypal fees (example: 182,96 EUR)
# - good example: https://my.sevdesk.de/ex/detail/id/75919037

# Scenario 16, refund from jlcpcb for components beeing cheaper then expected (Name: jlcpcb.com, Description: jlcpcb.com - jlcpcb.com - Refund from Jlcpcb.com)
# - refund is coming in multiple days after the initial purchase
# - ideally system should automatically book the refund in combination with the initial purchase and ask for an updated invoice
# - good example: https://my.sevdesk.de/ex/detail/id/76192157

# Scenario 17, purchase from cosplayshop.be via paypal (Name: Select Style, Description: Bestellung 118084 / TXID 0XK80854YL299572G)
# - (after 2 days) search for emails with pdf attachments that have the value of the transactions
# - (after 2 days) when that fails, search for pdf files in cloud storage with the transaction value and the date of the transaction (or a date within the range)
# - (after 7 days) when that fails, search for emails with the value of the transaction (excluding paypal emails). Send pdfs of those emails to chat and ask if any of them is the invoice for the transaction. If user selects any of them, it will be processed as invoice for the transaction
# - (after 7 days) when that fails, user will be asked to upload the invoice pdf to chat for processing
# - (every 3 days after that during the week), user will be reminded to upload the invoice pdf to chat for processing

# Scenario 18, hostelworld (Name: WWW.HOSTELWORLD.COM,DUBLIN, Description: WWW.HOSTELWORLD.COM,DUBLIN - WWW.HOSTELWORLD.COM,DUBLIN)
# - no invoice pdf send via email and also apparently no invoice available via web interface
# - instead search for email with value of transaction in the email, save as pdf and process as voucher

# special scenarios:
# - amazon: complicated mix of invoices and splitting invoices. Automated only possible with access to api or web interface/web scraper, else manual, order by order
#    - possible solution: (without api access) if amazon order detected and older then 1 week ago, ask for invoice pdfs via chat and all messages send to the thread are processed as invoice pdfs for this order