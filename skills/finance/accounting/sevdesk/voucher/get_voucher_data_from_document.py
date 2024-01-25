################

# Default Imports

################
import sys
import os
import re
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.intelligence.ask_llm import ask_llm
from skills.intelligence.load_systemprompt import load_systemprompt
from skills.pdf.pdf_to_image import pdf_to_image
from skills.finance.accounting.sevdesk.contact.add_contact import add_contact
from skills.finance.accounting.sevdesk.contact.search_contact import search_contact
from skills.finance.accounting.sevdesk.contact.add_contact_address import add_contact_address
from skills.finance.accounting.sevdesk.voucher.get_voucher_data_from_pdf_metadata import get_voucher_data_from_pdf_metadata
from skills.pdf.pdf_to_text import pdf_to_text
import asyncio
from datetime import datetime


def get_voucher_data_from_document(
        filepath: str,
        transaction: dict,
        default_currency: str = "EUR",
        save_to_json: bool = False
        ) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Extracting voucher data from the document ...")

        # check if the file exists
        if not os.path.isfile(filepath):
            add_to_log(f"File not found: {filepath}", state="error")
            return {"error": [f"File not found: {filepath}"]}
        

        # check if the file has already been processed
        voucher_data = get_voucher_data_from_pdf_metadata(filepath)
        if voucher_data:
            if voucher_data and voucher_data.get("voucher"):
                add_to_log(f"File has already been processed. Returning voucher data...", state="success", module_name="SevDesk")
                return voucher_data
            
        
        # load the systemprompt
        systemprompt = load_systemprompt(special_usecase="bank_transactions_processing/sevdesk_germany/extract_invoice_data", extra_data={"transaction": transaction})

        message = ""

        # extract text from the pdf and attach to request to LLM for better accuracy
        pdf_ocr_text = pdf_to_text(filepath=filepath)
        if pdf_to_image:
            message += f"# Text from PDF (via OCR):\n{pdf_ocr_text}\n\n"

        # check if the filepaths are pdf. If so, make images from all pages
        image_file_paths = []
        if filepath.endswith(".pdf"):
            image_file_paths += pdf_to_image(filepath=filepath)
        else:
            image_file_paths.append(filepath)

        # send the images to the LLM and get the voucher data
        file_paths_string = " ".join(image_file_paths)

        message += f"# Screenshots from PDF:\n{file_paths_string}"

        message_history = [
                        {"role": "system", "content":systemprompt},
                        {"role": "user", "content":message}
                        ]
        
        voucher_data = asyncio.run(ask_llm(
            bot={
                "user_name": "finn", 
                "system_prompt": systemprompt, 
                "creativity": 0, 
                "model": "gpt-4"
            },
            message_history=message_history,
            response_format="json"
        )
        )

        if not voucher_data:
            add_to_log("Failed to extract voucher data from the document.", state="error", module_name="SevDesk")
            return {"error": ["Failed to extract voucher data from the document."]}
        
        # if transaction_total_equals_voucher_total is False, ask the user to manually process the voucher
        if voucher_data.get("transaction_total_equals_voucher_total") == False:
            add_to_log("transaction_total_equals_voucher_total is False. Voucher does not seem to be match...",state="error", module_name="SevDesk")
            return {"error": ["transaction_total_equals_voucher_total is False. Voucher does not seem to be match..."]}

        # set the sumGross of each position
        if not voucher_data.get("voucherPosSave"):
            add_to_log("No voucher positions found.", state="error", module_name="SevDesk")

            if save_to_json:
                # save the voucher_data to a json file in the same folder as the pdf
                voucher_data_filepath = re.sub("\.pdf$", ".json", filepath)
                with open(voucher_data_filepath, "w") as file:
                    json.dump(voucher_data, file, indent=4)

            return {"error": ["No voucher positions found."]}
        else:
            if voucher_data.get("voucherPosSave"):
                for position in voucher_data["voucherPosSave"]:
                    if position.get("taxRate") and position.get("taxRate") > 0:
                        position["sumGross"] = round(position["sumNet"] * (1 + (position["taxRate"] / 100)),2)
                    else:
                        position["sumGross"] = position["sumNet"]
                    
                    position["net"] = False # so that sumGross is used instead of sumNet by sevdesk


        # check for every position, if the accountingType was wrongly set (especially Privateinlagen and Privatentnahmen switched)
        if voucher_data.get("voucherPosSave"):
            for position in voucher_data["voucherPosSave"]:
                # if Privateinlagen (37) and the value is negative, set the accountingType to Privatentnahmen (76)
                if position.get("accountingType") and position["accountingType"].get("id") == "37" or position["accountingType"].get("id") == 37:
                    if voucher_data["voucher"]["creditDebit"] == "C":
                        add_to_log("Voucher accountingType is 'Privateinlagen' (37) and the value is negative ('credit'). Setting the accountingType to Privatentnahmen (76)...")
                        position["accountingType"]["id"] = 76
                
                # if Privatentnahmen (76) and the value is positive, set the accountingType to Privateinlagen (37)
                elif position.get("accountingType") and position["accountingType"].get("id") == "76" or position["accountingType"].get("id") == 76:
                    if voucher_data["voucher"]["creditDebit"] == "D":
                        add_to_log("Voucher accountingType is 'Privatentnahmen' (76) and the value is positive ('debit'). Setting the accountingType to Privateinlagen (37)...")
                        position["accountingType"]["id"] = 37


        # set the status to unpaid
        voucher_data["voucher"]["status"] = "100" # 100 = unpaid, 50 == draft, 150 == transfered, 750 == partially paid, 1000 == paid

        # if the currency is not default currency, set propertyForeignCurrencyDeadline
        if voucher_data["voucher"].get("currency") != default_currency:
            add_to_log("Setting the real exchange rate...")
            # set the voucher_data["voucher"]["propertyExchangeRate"], based on the total of the transaction and the sum of all sumGross values of the voucher positions
            total_sum_net = 0
            if voucher_data.get("voucherPosSave"):
                for position in voucher_data["voucherPosSave"]:
                    if not position.get("sumGross"):
                        if position.get("taxRate") and position.get("taxRate") > 0:
                            position["sumGross"] = round(position["sumNet"] * (1 + position["taxRate"] / 100),2)
                        else:
                            position["sumGross"] = position["sumNet"]
                    # if credit, subtract, if debit, add
                    if voucher_data["voucher"]["creditDebit"] == "C":
                        total_sum_net -= position["sumGross"]
                    else:
                        total_sum_net += position["sumGross"]
                # calculate the exchange rate
                voucher_data["voucher"]["propertyExchangeRate"] = abs(float(transaction["amount"])) / abs(total_sum_net)

                # if the bill_amount is the same as total_sum_net, set the status to paid
                if transaction.get("bill_amount") and total_sum_net == float(transaction["bill_amount"]):
                    add_to_log("The bill_amount is the same as total_sum_net. Setting the status to paid...")
                    voucher_data["voucher"]["status"] = "1000"
                    add_to_log(f"voucher: {str(voucher_data)}")
                else:
                    add_to_log("The bill_amount is not the same as total_sum_net.")
                    add_to_log(f"transaction: {str(transaction)}")
                    add_to_log(f"total_sum_net: {total_sum_net}")

        else:
            # if the currency is default currency, check if the transaction value is the same as the sum of all sumGross values of the voucher positions
            total_sum_net = 0
            if voucher_data.get("voucherPosSave") and len(voucher_data["voucherPosSave"])>0:
                for position in voucher_data["voucherPosSave"]:
                    if not position.get("sumGross"):
                            if position.get("taxRate") and position.get("taxRate") > 0:
                                position["sumGross"] = round(position["sumNet"] * (1 + position["taxRate"] / 100),2)
                            else:
                                position["sumGross"] = position["sumNet"]
                    # if credit, subtract, if debit, add
                    if voucher_data["voucher"]["creditDebit"] == "C":
                        total_sum_net -= position["sumGross"]
                    else:
                        total_sum_net += position["sumGross"]

                # scenario: often the voucher value is one cent off. Therefore always use the transaction["amount"] as the voucher value
                # adapt the value of the first position, so that the sumGross of all positions is equal to the transaction["amount"]
                if transaction.get("amount") and total_sum_net != float(transaction["amount"]):
                    add_to_log("The transaction value is not the same as the sum of all sumGross values of the voucher positions. Adapting the value of the first position...")
                    voucher_data["voucherPosSave"][0]["sumGross"] = (total_sum_net - float(transaction["amount"])) + voucher_data["voucherPosSave"][0]["sumGross"]
                    total_sum_net = float(transaction["amount"])

                if transaction and total_sum_net == float(transaction["amount"]):
                    add_to_log("The transaction value is the same as the sum of all sumGross values of the voucher positions. Setting the status to paid...")
                    voucher_data["voucher"]["status"] = "1000" # 100 = unpaid, 50 == draft, 150 == transfered, 750 == partially paid, 1000 == paid
    

        # replace name of the supplier/customer with the ID of the supplier/customer in sevDesk (and create the supplier/customer if it doesn't exist yet)
        # find the supplier in sevDesk
        params = {}
        # Access and set contact data using the new key
        if voucher_data["voucher"]["contact"].get("name"):
            params["name"] = voucher_data["voucher"]["contact"]["name"]
        if voucher_data["voucher"]["contact"].get("surename"):
            params["surename"] = voucher_data["voucher"]["contact"]["surename"]
        if voucher_data["voucher"]["contact"].get("familyname"):
            params["familyname"] = voucher_data["voucher"]["contact"]["familyname"]

        # search for existing contact in sevDesk
        contact = search_contact(**params)

        # Create a new contact
        if not contact and voucher_data["voucher"].get("contact"):
            add_to_log("Contact not found. Creating a new contact ...", module_name="SevDesk")
            contact = add_contact(**voucher_data["voucher"]["contact"])

            # Create the address and link it to the contact
            voucher_data["voucher"]["contact"]["contact_id"] = contact["id"]
            add_contact_address(contact_id=contact["id"], **voucher_data["voucher"]["contact"]["address"])

        # link the contact to the voucher
        voucher_data["voucher"]["supplier"] = {}
        voucher_data["voucher"]["supplier"]["id"] = contact["id"]
        voucher_data["voucher"]["supplier"]["objectName"] = "Contact"

        # Remove the contact details from the voucher data because they are not needed for the API call
        voucher_data["voucher"].pop("contact")

        # once the data are extracted, delete the temporary images
        for image_file_path in image_file_paths:
            os.remove(image_file_path)

        # save product_sales data to a json file
        if voucher_data.get("product_sales") and len(voucher_data["product_sales"]) > 0:
            # load the existing product_sales_data.json file and add new sales to it and update total sales
            sales_data_dir = f"{main_directory}/temp_data/sales"
            os.makedirs(sales_data_dir, exist_ok=True)
            product_sales_data_filepath = os.path.join(sales_data_dir, "product_sales_data.json")
            if os.path.isfile(product_sales_data_filepath):
                with open(product_sales_data_filepath, "r") as file:
                    product_sales_data = json.load(file)
            else:
                product_sales_data = {"product_sales": [], "total_income": 0}

            # add each of the new sales to the product_sales_data and update total_income
            for product_sale in voucher_data["product_sales"]:
                product_sales_data["product_sales"].append(product_sale)
                product_sales_data["total_income"] += (product_sale["per_unit_price"] * product_sale["quantity"])

            # save the updated product_sales_data to a json file
            with open(product_sales_data_filepath, "w") as file:
                json.dump(product_sales_data, file, indent=4)

        # add target_folder ("YYYY/YYYY_MM") to the voucher_data, based on voucherDate ("YYYY-MM-DD")
        # parse the voucherDate using datetime or dateutil
        try:
            voucher_date = datetime.strptime(voucher_data["voucher"]["voucherDate"], "%d.%m.%Y")
        except ValueError:
            voucher_date = datetime.strptime(voucher_data["voucher"]["voucherDate"], "%Y-%m-%d")
        
        # move to Income or Expense folder based on creditDebit
        if voucher_data["voucher"]["is_internal_transfer"] == True or voucher_data["voucher"]["is_internal_transfer"] == "TRUE":
            voucher_data["voucher"]["target_folder"] = f"Internal Transfers/{voucher_date.year}/{voucher_date.year}_{voucher_date.month:02d}"
        elif voucher_data["voucher"]["creditDebit"] == "C":
            voucher_data["voucher"]["target_folder"] = f"Expenses/{voucher_date.year}/{voucher_date.year}_{voucher_date.month:02d}"
        else:
            voucher_data["voucher"]["target_folder"] = f"Income/{voucher_date.year}/{voucher_date.year}_{voucher_date.month:02d}"
            

        add_to_log(f"Successfully extracted voucher data from the document", state="success", module_name="SevDesk")

        if save_to_json:
            # save the voucher_data to a json file in the same folder as the pdf
            voucher_data_filepath = re.sub("\.pdf$", ".json", filepath)
            with open(voucher_data_filepath, "w") as file:
                json.dump(voucher_data, file, indent=4)

        return voucher_data

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to extract voucher data from the document.", traceback=traceback.format_exc())
        return {"error": ["Failed to extract voucher data from the document."]}


if __name__ == "__main__":
    # process pdf files in the folder of the script
    pdf_files = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for file in os.listdir(script_dir):
        if file.endswith(".pdf"):
            pdf_files.append(os.path.join(script_dir, file))  # include the full path
    for pdf_file in pdf_files:
        get_voucher_data_from_document(pdf_file, save_to_json=True)