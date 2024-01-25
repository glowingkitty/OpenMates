import os
import sys
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from datetime import datetime
from skills.pdf.add_pdf_metatags import add_pdf_metatags
from skills.cloud_storage.dropbox.upload_file import upload_file

import json

def write_voucher_data_to_pdf_metadata(
        filepath: str, 
        data: dict, 
        title: str = None, 
        keywords: list = None, 
        save_json_if_error: bool = False,
        cloud_sync_path: str = None
        ) -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Writing the voucher data to the PDF metadata ...")

        # check if the file exists
        if not os.path.isfile(filepath):
            add_to_log(f"File not found: {filepath}", state="error")
            return False
        
        # Get the current time in the specified format
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Add 'processed_time' key with the current time and the data as metatags
        metadata = {'processed_time': current_time, 'data': data}
        if title:
            metadata['Title'] = title
        if keywords and isinstance(keywords, list):
            metadata['Keywords'] = ", ".join(keywords)
        elif keywords and isinstance(keywords, str):
            metadata['Keywords'] = keywords
        is_successful = add_pdf_metatags(filepath, metadata)
        
        if is_successful:
            add_to_log(f"Wrote voucher data to PDF metadata: {filepath}", state="success")
        else:
            add_to_log(f"Failed to write voucher data to PDF metadata: {filepath}", state="error")

        # if the key "errors" exists, save the data as a json
        if save_json_if_error and data.get("errors") and len(data.get("errors"))>0:
            json_filepath = filepath.replace(".pdf", ".json")
            with open(json_filepath, 'w') as outfile:
                json.dump(data, outfile, indent=4)
            add_to_log(f"Saved voucher data as json: {filepath}", state="success")

            if cloud_sync_path:
                # upload the json file to dropbox
                upload_file(
                    filepath=json_filepath, 
                    target_path=cloud_sync_path.replace(".pdf", ".json"),
                    delete_original=True
                    )
                add_to_log(f"Synced JSON file back to dropbox: {filepath}", state="success")
        
        
        return is_successful
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to write voucher data to PDF metadata", traceback=traceback.format_exc())
        return False
    

if __name__ == "__main__":
    current_folder_path = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(current_folder_path, "test_invoice.pdf")
    write_voucher_data_to_pdf_metadata(
        filepath=filepath, 
        data={'amount': 123.45, 'currency': 'EUR', 'invoice_number': 123456}, 
        title="Test Invoice 123456 (123.45 EUR)", 
        keywords=['invoice', 'Google', 'domain', 'hosting']
        )