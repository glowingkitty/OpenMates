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

from skills.email.googlemail.get_emails import get_emails
from typing import Tuple


def search_voucher_in_emails(transaction: dict) -> Tuple[str, str]:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Searching for voucher in emails...")
        
        add_to_log("Searching for emails with voucher PDF. Based on value of the transaction in PDF text, date of email,'invoice' in the email text ...")
        emails = get_emails(transaction=transaction, num_results=10000)

        pdf_vouchers = []
        # if multiple PDFs, try to auto filter out, based on if any of the PDFs contain "invoice" or "rechnung" in their filename
        if emails and len(emails) > 1:
            add_to_log(f"Found {len(emails)} emails with voucher PDF. Trying to auto filter out, based on if any of the PDFs contain 'invoice' or 'rechnung' in their filename ...", module_name="Finance")
            for email in emails:
                for attachment in email["attachments"]:
                    if attachment["filename"].endswith(".pdf"):
                        if "invoice" in attachment["filename"].lower() or "rechnung" in attachment["filename"].lower() or "receipt" in attachment["filename"].lower():
                            pdf_vouchers.append({
                                'attachment': attachment,
                                'date': email['datetime'],
                                'subject': email['subject']
                            })
                        else:
                            # Delete the attachment file
                            os.remove(attachment['filepath'])

        elif emails and len(emails) == 1:
            for attachment in emails[0]["attachments"]:
                if attachment["filename"].endswith(".pdf"):
                    pdf_vouchers.append({
                        'attachment': attachment,
                        'date': emails[0]['datetime'],
                        'subject': emails[0]['subject']
                    })

        else:
            add_to_log("No emails found with voucher PDF.", module_name="Finance", state="error")
            return None, None
        
        # now check if multiple PDFs are found, if so, ask user for the right one
        if len(pdf_vouchers)==1:
            add_to_log(f"Successfully found a single voucher in emails (Email: {pdf_vouchers[0]['date']} - {pdf_vouchers[0]['subject']}, File: {pdf_vouchers[0]['attachment']['filename']})", module_name="Finance", state="success")
            
            # return the filepath
            local_filepath = pdf_vouchers[0]['attachment']['filepath']
            cloud_filepath = None
            
            return local_filepath, cloud_filepath
        elif len(pdf_vouchers)>1:
            add_to_log(f"Found {len(pdf_vouchers)} PDFs in emails. Could not find a clear match. Therefore asking user in chat to provide PDF.", module_name="Finance")
            return None, None
        else:
            add_to_log("No PDFs found in emails.", module_name="Finance", state="error")
            return None, None

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to find voucher in emails.", traceback=traceback.format_exc())
        return None, None


if __name__ == "__main__":
    transaction = {
    }
    vouchers = search_voucher_in_emails(transaction=transaction)
    print(vouchers)