import os
import sys
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from skills.pdf.get_pdf_metatags import get_pdf_metatags


def get_voucher_data_from_pdf_metadata(filepath: str, delete_errors: bool = True) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Getting the voucher data from the PDF metadata ...")

        # check if the file exists
        if not os.path.isfile(filepath):
            add_to_log(f"File not found: {filepath}", state="error")
            return False
        
        metadata = get_pdf_metatags(filepath)

        if metadata.get("data") and metadata["data"].get("voucher"):
            if delete_errors:
                # delete the "error" and "errors" keys from the metadata
                if metadata["data"]["voucher"].get("error"):
                    del metadata["data"]["voucher"]["error"]
                if metadata["data"]["voucher"].get("errors"):
                    del metadata["data"]["voucher"]["errors"]

            add_to_log(f"Successfully got voucher data from PDF metadata: {filepath}", state="success")
            return metadata["data"]
        
        else:
            add_to_log(f"No voucher data found in PDF metadata: {filepath}")
            return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to check if the voucher PDF is processed", traceback=traceback.format_exc())
        return False

# Test the function with a sample file path
if __name__ == "__main__":
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_invoice.pdf")
    get_voucher_data_from_pdf_metadata(filepath)