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

from skills.pdf.find_text_in_pdf import find_text_in_pdf
from skills.finance.accounting.get_search_variations import get_search_variations
from datetime import datetime
from babel.dates import format_date

def search_in_pdf_file_and_name(file_paths: list, transaction: dict=None, search_variations: list = None) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Searching in PDF file and name...")
        add_to_log(f"Searching for {'search_variations' if search_variations else 'transaction' if transaction else ''} in file_paths ...")

        attempt = 1
        amount_with_comma_or_dot = True
        break_while_loop = False
        found_vouchers = []

        while attempt <= 2 and not break_while_loop:
            # get all possible search variations
            if search_variations is None and transaction is not None:
                search_variations = get_search_variations(transaction, amount_with_comma_or_dot=amount_with_comma_or_dot)
                
            elif search_variations is None and transaction is None:
                raise Exception("Either transaction or search_variations must be given.")
            

            # search for voucher in files
            for full_path in file_paths:
                # if the file is not a pdf, skip it
                if not full_path.endswith(".pdf"):
                    continue

                # search for all possible search variations in the file content
                add_to_log(f"Searching for query in PDF ({full_path}) ...")
                if find_text_in_pdf(full_path, search_variations):
                    add_to_log(f"Voucher file seems to be a match: {full_path}", state="success")
                    found_vouchers.append(full_path)

                # if the transaction value in float does not end with 00, there is no reason to try a second time
                if float(str(transaction["amount"]).replace("-", "")) % 1 != 0:
                    add_to_log(f"Transaction amount is not an integer. No need to search a second time.", module_name="Finance")
                    break_while_loop = True

                if found_vouchers:
                    break

                attempt += 1
                amount_with_comma_or_dot = False

        # if multiple vouchers were found, try to see if only som of them have "invoice" or "rechnung" or "receipt" or "beleg" in their filename
        # if so, filter out the ones that don't
        invoice_trigger_words = ["invoice", "rechnung", "receipt", "beleg"]
        if transaction and len(found_vouchers) > 1:
            add_to_log(f"Found {len(found_vouchers)} matching vouchers. Trying to auto filter out to only find real invoices ...", module_name="Finance")
            filtered_found_vouchers = []
            for voucher_path in found_vouchers:
                file_name = os.path.basename(voucher_path)
                for word in invoice_trigger_words:
                    if word in file_name.lower():
                        filtered_found_vouchers.append(voucher_path)
                        break
            
            if len(filtered_found_vouchers) > 0 and len(filtered_found_vouchers) < len(found_vouchers):
                add_to_log(f"Successfully filtered out to only find real invoices. Found {len(filtered_found_vouchers)} matching vouchers.", module_name="Finance", state="success")
                found_vouchers = filtered_found_vouchers
            else:
                add_to_log(f"Filtering by keywords in filenames didn't change anything.")

            # if still multiple vouchers were found, see if any of the voucher has the exact date of the transaction in its filename
            if len(found_vouchers) > 1:
                date_options = []
                entry_date = datetime.strptime(transaction["entryDate"], "%Y-%m-%dT%H:%M:%S%z")

                date_formats = [
                    "dd.MM.yyyy",
                    "d.MM.yyyy",
                    "yyyy-MM-dd",
                    "yyyy/MM/dd",
                    "d. MMMM yyyy",
                    "d MMMM yyyy",
                    "d MMM yyyy",
                    "MMMM dd, yyyy",
                    "yyyy, MMMM d",
                ]

                locales = ["en", "de"]
                for locale in locales:
                    for date_format in date_formats:
                        date_options.append(format_date(entry_date, date_format, locale=locale))
                        

                filtered_found_vouchers = []
                for voucher_path in found_vouchers:
                    file_name = os.path.basename(voucher_path)
                    for date in date_options:
                        if date in file_name:
                            add_to_log(f"Found date in filename: {date} in {file_name}")
                            filtered_found_vouchers.append(voucher_path)
                            break

                if len(filtered_found_vouchers) == 1:
                    add_to_log('Successfully filtered out to only find the real voucher. Found 1 matching voucher.', module_name="Finance", state="success")
                    found_vouchers = filtered_found_vouchers
                else:
                    add_to_log(f"Filtering by date in filenames didn't change anything.")
        
        add_to_log(f"Fount {len(found_vouchers)} matching vouchers when searching in the PDF file and name.", module_name="Finance", state="success")
        return found_vouchers
    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to search in PDF file and name.", traceback=traceback.format_exc())
        return None