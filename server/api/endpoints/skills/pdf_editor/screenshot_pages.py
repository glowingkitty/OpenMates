################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


import requests
from PyPDF2 import PdfReader
from pdf2image import convert_from_path, convert_from_bytes
import io
from typing import List
import tempfile
from PIL import Image
import uuid


def screenshot_pages(
        pdf_path: str=None,
        pdf_data: bytes=None,
        max_length_px: int = 1500,
        pages: list=None
    ) -> List[str]:
    # Check the type of pdf_path and pdf_data
    if pdf_path is not None:
        if pdf_path.startswith('http') or pdf_path.startswith('https'):
            # Download the PDF from the URL
            response = requests.get(pdf_path)
            pdf_file = io.BytesIO(response.content)
        else:
            # Open the PDF file from the local path
            pdf_file = open(pdf_path, 'rb')
    elif pdf_data is not None:
        # Convert the bytes to a file-like object
        pdf_file = io.BytesIO(pdf_data)
    else:
        raise ValueError('Either pdf_path or pdf_data must be provided')

    # Read the PDF file
    pdf = PdfReader(pdf_file)

    # Convert pages to a list of page numbers
    if pages is not None:
        pages = list(pages)
    else:
        pages = list(range(1, len(pdf.pages) + 1))

    # List to store image file paths
    image_paths = []

    # Generate a random folder name
    random_folder_name = str(uuid.uuid4())
    base_dir = main_directory+'server/api/endpoints/skills/pdf_editor/temp_data/'

    # Create the base directory if it doesn't exist
    os.makedirs(base_dir, exist_ok=True)

    target_dir = os.path.join(base_dir, random_folder_name)

    # Create the target directory
    os.makedirs(target_dir, exist_ok=True)

    # Convert each page to an image
    for page_num in pages:
        pdf_file.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
            temp_pdf.write(pdf_file.read())
        images = convert_from_path(temp_pdf.name, first_page=page_num, last_page=page_num)
        for i, image in enumerate(images):
            # Include the target directory in the image path
            image_path = os.path.join(target_dir, f'page_{page_num}_{i}.png')

            # Resize the image if its longest side is greater than max_length_px
            if max(image.size) > max_length_px:
                image.thumbnail((max_length_px, max_length_px))

            # Save the image
            image.save(image_path, 'PNG')

            image_paths.append(image_path)
        os.remove(temp_pdf.name)  # delete the temporary file

    # Close the PDF file
    pdf_file.close()

    return image_paths


# Test the function
if __name__ == '__main__':
    pdf_path = 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
    images = screenshot_pages(pdf_path=pdf_path)
    print(images)