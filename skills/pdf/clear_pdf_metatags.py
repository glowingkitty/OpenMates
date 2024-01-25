from PyPDF2 import PdfReader, PdfWriter
import sys
import os
import re
import traceback

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

def clear_pdf_metatags(filepath: str) -> None:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Clearing PDF metadata ...")
        
        with open(filepath, 'rb') as file:
            reader = PdfReader(file)
            writer = PdfWriter()
            
            for page in reader.pages:
                writer.add_page(page)
            
            writer.info = {}
            
        with open(filepath, 'wb') as file:
            writer.write(file)
            
        add_to_log("Successfully cleared PDF metadata.", state="success")
        
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to clear PDF metadata", traceback=traceback.format_exc())

if __name__ == "__main__":
    target_folder = os.path.dirname(os.path.abspath(__file__))

    for dirpath, dirnames, filenames in os.walk(target_folder):
        for filename in filenames:
            if filename.endswith(".pdf"):
                filepath = os.path.join(dirpath, filename)
                clear_pdf_metatags(filepath=filepath)