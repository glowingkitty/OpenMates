from PyPDF2 import PdfReader
import sys
import os
import re
import ast

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

import json

def get_pdf_metatags(filepath: str, save_to_json: bool = False) -> dict:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Reading PDF metadata ...")
        
        with open(filepath, 'rb') as file:
            reader = PdfReader(file)
            metadata = reader.metadata
            # Remove leading '/' from key names and convert back to original format if possible
            metatags = {key[1:]: ast.literal_eval(metadata[key]) if isinstance(metadata[key], str) and re.match(r'^True$|^False$|^None$|^\[.*\]$|^{.*}$', metadata[key]) else metadata[key] for key in metadata}  
        add_to_log(f"Successfully read PDF metadata.", state="success", module_name="PDF")

        if save_to_json:
            json_filepath = re.sub(r'\.pdf$', '.json', filepath)
            with open(json_filepath, 'w') as file:
                json.dump(metatags, file, indent=4)
            add_to_log(f"Successfully saved PDF metadata to {json_filepath}.", state="success", module_name="PDF")

        return metatags
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to read PDF metadata", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    current_folder_path = os.path.dirname(os.path.abspath(__file__))

    for filename in os.listdir(current_folder_path):
        if filename.endswith(".pdf"):
            filepath = os.path.join(current_folder_path, filename)
            get_pdf_metatags(filepath=filepath, save_to_json=True)