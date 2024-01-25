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

from PyPDF2 import PdfReader

def find_text_in_pdf(filepath: str, search: list) -> bool:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        # Ensure all search terms are strings
        if not isinstance(search, list):
            raise ValueError("Search must be a list of strings or a list of lists of strings")
        else:
            search = [str(item).lower() if not isinstance(item, list) else [str(subitem).lower() for subitem in item] for item in search]

        add_to_log(f"Searching for query in PDF ...")

        # Explainaion of search:
        # - if search is a list of strings, any of the strings must be found in the pdf (OR)
        # - if search is a list of lists of strings, all of the strings in each list must be found in the pdf (AND)

        # Open the PDF file in read-binary mode
        filename = os.path.basename(filepath)
        with open(filepath, 'rb') as file:
            # Create a PDF file reader object
            pdf_reader = PdfReader(file)

            # Iterate over all the pages and search for the text
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text_in_page = page.extract_text().lower()+" "+filename

                # Implement search_or functionality
                for entry in search:
                    if isinstance(entry, list):
                        if all(e.lower() in text_in_page.lower() for e in entry):
                            add_to_log(f"Texts {entry} found in PDF: {filepath}", state="success")
                            return True
                        if all(e.lower().replace(' ','') in text_in_page.lower().replace(' ','') for e in entry):
                            add_to_log(f"Texts {entry} found in PDF: {filepath}", state="success")
                            return True
                    elif entry in text_in_page:
                        add_to_log(f"Text '{entry}' found in PDF: {filepath}", state="success")
                        return True

        add_to_log(f"Query not found in PDF: {filepath}", state="error")
        return False

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to search text in pdf", traceback=traceback.format_exc())
        return False
    
    
if __name__ == "__main__":
    # process every pdf file in the same directory as this script and its subdirectories
    dir_path = os.path.dirname(os.path.realpath(__file__))
    found_in_paths = []
    for root, dirs, files in os.walk(dir_path):
        for filename in files:
            if filename.endswith(".pdf"):
                full_path = os.path.join(root, filename)
                found = find_text_in_pdf(full_path, [[
                    "300,00",
                    "5. Dezember 2023",
                    "rechnung",
                ],])
                if found:
                    found_in_paths.append(full_path)
    
    print(found_in_paths)