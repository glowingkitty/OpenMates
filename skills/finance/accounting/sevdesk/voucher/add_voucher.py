################

# Default Imports

################
import sys
import os
import re
import requests
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.accounting.sevdesk.voucher.get_voucher_data_from_document import get_voucher_data_from_document
from skills.finance.accounting.sevdesk.voucher.write_voucher_data_to_pdf_metadata import write_voucher_data_to_pdf_metadata
from skills.finance.accounting.sevdesk.voucher.add_transaction_to_voucher import add_transaction_to_voucher

# https://api.sevdesk.de/#tag/Voucher/operation/createVoucherByFactory

# more details: see file "my_profile/systemprompts/special_usecases/bank_transactions_processing/sevdesk_germany/extract_invoice_data.md"

from skills.finance.accounting.sevdesk.voucher.get_voucher import get_voucher
import copy
from typing import List, Dict

def add_voucher(
        filepath: str,
        transactions: List[Dict],
        primary_transaction: Dict,
        add_to_transaction: bool = True,
        cloud_sync_path: str = None
        ) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Processing the voucher ...")

        # check if the file exists
        if not os.path.isfile(filepath):
            add_to_log(f"File not found: {filepath}", state="error")
            return None
        
        # Get the voucher data from the document
        voucher_data = get_voucher_data_from_document(filepath=filepath, transaction=primary_transaction)
        
        if not voucher_data.get("voucher"):
            add_to_log(f"Failed to get voucher data from document: {filepath}", state="error")
            return None
        
        # check if the voucher already exists in sevDesk. If yes, skip it
        if voucher_data["voucher"].get("id"):
            # check if the voucher with the id exists. if not, remove the id and continue
            if get_voucher(voucher_data["voucher"]["id"]):
                add_to_log(f"Voucher already exists in sevDesk. Skipping it.",state="success")
                return voucher_data
            else:
                add_to_log(f"Voucher with ID {voucher_data['voucher']['id']} does not exist in sevDesk. Removing the ID and continuing.")
                del voucher_data["voucher"]["id"]


        # Placeholder for sevDesk API credentials and endpoint
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")


        # Upload the file to sevDesk
        with open(filepath, 'rb') as file:
            files = {'file': file}
            response = requests.post('https://my.sevdesk.de/api/v1/Voucher/Factory/uploadTempFile', files=files, headers={'Authorization': api_key})
            if response.status_code != 201:
                process_error(f"Failed to upload the file. Status code: {response.status_code}: {response.text}")
                return None
            upload_data = response.json()
            voucher_data["filename"] = upload_data['objects']['filename']

            
        # Save the voucher details to sevDesk
        headers = {'Authorization': api_key, 'Content-Type': 'application/json'}
        # set the status of the voucher to "100" (unpaid), before sending it to the API, so that later the voucher can be booked to a transaction and they are linked
        voucher_data_for_sevdesk = copy.deepcopy(voucher_data)
        if voucher_data_for_sevdesk["voucher"].get("status") == "1000":
            voucher_data_for_sevdesk["voucher"]["status"] = "100"

        response = requests.post('https://my.sevdesk.de/api/v1/Voucher/Factory/saveVoucher', headers=headers, data=json.dumps(voucher_data_for_sevdesk))
            
        if response.status_code != 201:
            process_error(f"Failed to save the voucher. Status code: {response.status_code}: {response.text}")
            return None
        save_data = response.json()
        voucher_data["voucher"]["id"] = save_data.get('objects', {}).get("voucher", {}).get("id")

        add_to_log(f"Successfully uploaded the receipt with ID: {voucher_data['voucher']['id']}", state="success")
        

        # Match the voucher to the corresponding transactions
        # add all transactions to the voucher (multiple in case of a PayPal transaction, else typicall only one)
        if add_to_transaction and transactions:
            for transaction in transactions:
                success = add_transaction_to_voucher(voucher_data, transaction)
                if not success:
                    # check if error key is present, else create it
                    if not voucher_data.get("errors"):
                        voucher_data["errors"] = []
                    voucher_data["errors"].append(f"Failed to find a matching sevdesk transaction when trying to add the transaction ({transaction}) to the voucher")


        # if no error is present, mark the voucher as successfully processed
        if not voucher_data.get("errors"):
            voucher_data["processed"] = "success"
            
        write_voucher_data_to_pdf_metadata(
            filepath=filepath,
            data=voucher_data,
            save_json_if_error=True,
            cloud_sync_path=cloud_sync_path
            )

        return voucher_data

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to add receipt to sevDesk", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(current_dir, "invoice.pdf")
    add_voucher(filepath=filepath, save_to_json=True)