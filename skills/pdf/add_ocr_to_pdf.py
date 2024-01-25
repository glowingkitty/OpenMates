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

import ocrmypdf


def add_ocr_to_pdf(filepath: str):
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Processing PDF and adding OCR ...")

        # Add OCR to the PDF
        ocrmypdf.ocr(filepath, filepath)

        add_to_log(f"Successfully added OCR to PDF: {filepath}", state="success")
        return filepath

    except KeyboardInterrupt:
        shutdown()
    
    except ocrmypdf.exceptions.PriorOcrFoundError:
        add_to_log("OCR already found in PDF, skipping ...", state="success")
        return filepath

    except Exception:
        process_error("Failed to add ocr to pdf", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    # process every pdf file in the same directory as this script and its subdirectories
    dir_path = os.path.dirname(os.path.realpath(__file__))
    for root, dirs, files in os.walk(dir_path):
        for filename in files:
            if filename.endswith(".pdf"):
                full_path = os.path.join(root, filename)
                add_ocr_to_pdf(full_path)