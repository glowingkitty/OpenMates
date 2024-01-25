import sys
import os
import re
import traceback

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from skills.pdf.get_pdf_metatags import get_pdf_metatags
from skills.pdf.clear_pdf_metatags import clear_pdf_metatags
from skills.pdf.add_pdf_metatags import add_pdf_metatags

def remove_pdf_metatag(filepath: str, key: str) -> None:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log(f"Removing '{key}' from PDF metadata ...")
        
        # Get all existing metatags
        existing_metatags = get_pdf_metatags(filepath)
        
        # Clear all metatags
        clear_pdf_metatags(filepath)
        
        # Remove the key from existing metatags
        if key in existing_metatags:
            del existing_metatags[key]
        
        # Add all metatags again, except the key which should be removed
        add_pdf_metatags(filepath, existing_metatags)
        
        add_to_log(f"Successfully removed {key} from PDF metadata.", state="success")
        
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to remove {key} from PDF metadata", traceback=traceback.format_exc())

if __name__ == "__main__":
    current_folder_path = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(current_folder_path, "test_invoice.pdf")
    remove_pdf_metatag(filepath=filepath, key="test_list")