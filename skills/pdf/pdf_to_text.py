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

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io


def pdf_to_text(filepath: str = None, file_content: str = None) -> str:
    try:
        add_to_log(module_name="PDF", color="orange", state="start")
        add_to_log("Extracting text from PDF ...")

        if not filepath and not file_content:
            raise ValueError(f"Either filepath or filecontent must be provided.")
        
        if not file_content:
            # check if file exists
            if not os.path.isfile(filepath):
                raise FileNotFoundError(f"PDF file not found: {filepath}")
        
            with open(filepath, "rb") as file:
                file_content = file.read()

        pdf_text = ""
        with fitz.open(stream=file_content, filetype="pdf") as pdf:
            for page_num in range(len(pdf)):
                page = pdf[page_num]
                text = page.get_text()
                if text.strip():
                    pdf_text += text
                else:
                    for img in page.get_images(full=True):
                        xref = img[0]
                        try:
                            if sys.platform == "darwin":
                                pytesseract.pytesseract.tesseract_cmd = r'/opt/homebrew/bin/tesseract'
                            base_image = pdf.extract_image(xref)
                            image_bytes = base_image["image"]
                            image = Image.open(io.BytesIO(image_bytes))
                            text = pytesseract.image_to_string(image, lang='eng')
                            pdf_text += text
                        except Exception as e:
                            process_error(
                                file_name=os.path.basename(__file__),
                                when_did_error_occure=f"While processing image {xref}",
                                traceback=traceback.format_exc(),
                                file_path=full_current_path,
                                local_variables=locals(),
                                global_variables=globals()
                            )
                            continue

        if pdf_text.strip():
            add_to_log(f"Successfully extracted text from PDF", state="success")
            return pdf_text
        else:
            add_to_log(f"No text found in PDF", state="error")
            return None

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to extract text from PDF.", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    # process pdf files in the folder of the script
    pdf_files = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for file in os.listdir(script_dir):
        if file.endswith(".pdf"):
            pdf_files.append(os.path.join(script_dir, file))  # include the full path
    for pdf_file in pdf_files:
        text = pdf_to_text(pdf_file)

        # save as markdown file
        md_file_name = os.path.splitext(pdf_file)[0] + '.md'  # change .pdf to .md
        with open(md_file_name, 'w') as md_file:
            md_file.write(text)