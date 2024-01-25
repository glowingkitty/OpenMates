from PyPDF2 import PdfReader, PdfWriter
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *


def add_pdf_metatags(filepath: str, metadata: dict) -> bool:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Adding metadata to PDF ...")
        
        with open(filepath, 'rb') as file:
            reader = PdfReader(file)
            writer = PdfWriter()
            for page in reader.pages:
                try:
                    writer.add_page(page)
                except AssertionError:
                    add_to_log("Failed to add a page to PDF, skipping", state="error")
                    continue
            
            # Ensure metadata keys start with '/' and all values are strings
            metadata = {('/' + k if not k.startswith('/') else k): str(v) for k, v in metadata.items()}
            
            # Add metadata
            writer.add_metadata(metadata)
            
            # Write out the PDF with new metadata
            with open(filepath, 'wb') as outfile:
                writer.write(outfile)
        
        add_to_log("Successfully added metadata to PDF", state="success")
        return True
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to add metadata to PDF", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    current_folder_path = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(current_folder_path, "test_invoice.pdf")
    add_pdf_metatags(filepath=filepath, metadata={
        'Author': 'John Doeee', 
        'Title': 'Sample PDF',
        'has_been_processed': True,
        'invoice_number': 102123,
        'test_list': [1, 2, 3],
        'test_dict': {'a': 1, 'b': 2},
        'value':None
        })