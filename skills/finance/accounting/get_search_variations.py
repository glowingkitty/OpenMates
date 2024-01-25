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
from babel.dates import format_date
from datetime import datetime, timedelta
import json
import subprocess

def get_search_variations(transaction: dict, amount_with_comma_or_dot: bool = True,export_for_testing:bool = False) -> list:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Getting search variations...")

        search_variations = []
        # add all possible search variations to list
        invoice_text_options_variable_day = ["invoice", "rechnung", "receipt", "beleg"]
        invoice_text_options_same_day = ["transaction statement", "bon"]
        invoice_text_options = invoice_text_options_variable_day + invoice_text_options_same_day
        amount_options = []
        date_options = []

        # if transaction has "bill_amount", add it to the search options, else add "amount"
        if "bill_amount" in transaction and transaction["bill_amount"] is not None:
            if "." in str(transaction["bill_amount"]) or "," in str(transaction["bill_amount"]):
                amount = float(str(transaction["bill_amount"]).replace("-", ""))
            else:
                amount = int(str(transaction["bill_amount"]).replace("-", ""))
        else:
            if "." in str(transaction["amount"]) or "," in str(transaction["amount"]):
                amount = float(str(transaction["amount"]).replace("-", ""))
            else:
                amount = int(str(transaction["amount"]).replace("-", ""))

        if amount_with_comma_or_dot:
            amount_options.append(f"{amount:.2f}")
            amount_options.append(f"{amount:.2f}".replace(".", ","))
        else:
            amount_options.append(str(amount))

        # add all possible dates (+- 7 days around the transaction["entryDate"]) in the formats DD-MM-YYYY, YYYY-MM-DD, YYYY/MM/DD
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
        for i in range(-7,8):
            date = entry_date + timedelta(days=i)
            for locale in locales:
                for date_format in date_formats:
                    date_options.append(format_date(date, date_format, locale=locale))


        # add all possible search variations to list
        entry_date_obj = entry_date.date()
        for amount in amount_options:
            for keyword in transaction["keywords"]:
                for date in date_options:
                    for invoice_text in invoice_text_options:
                        # Convert date to a date object
                        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y"):
                            try:
                                date_obj = datetime.strptime(date, fmt).date()
                                break
                            except ValueError:
                                pass

                        # if invoice_text_option is "transaction statement" or "bon", only check for the same day (not the days before and after)
                        if invoice_text in invoice_text_options_same_day and date_obj != entry_date_obj:
                            continue
                        
                        search_variations.append([amount, date, invoice_text, keyword])

        add_to_log("Successfully created search variations", state="success")
        if export_for_testing:
            with open('search_variations.json', 'w') as f:
                json.dump(search_variations, f, indent=4)
            subprocess.run(["code", "search_variations.json"])
        return search_variations
    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to create search variations.", traceback=traceback.format_exc())
        return None, None
    

if __name__ == "__main__":
    from skills.finance.accounting.enrich_transaction_data import enrich_transaction_data

    transaction = {
    }

    transaction = enrich_transaction_data(transaction)

    search_variations = get_search_variations(transaction)
    with open('search_variations.json', 'w') as f:
        json.dump(search_variations, f, indent=4)
    subprocess.run(["code", "search_variations.json"])