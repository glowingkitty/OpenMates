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
from pdf2image import convert_from_bytes
import io
from typing import List
import uuid


def get_pdf_file(pdf_path: str=None, pdf_data: bytes=None):
    if pdf_path is not None:
        if pdf_path.startswith('http') or pdf_path.startswith('https'):
            response = requests.get(pdf_path)
            return io.BytesIO(response.content)
        else:
            return open(pdf_path, 'rb')
    elif pdf_data is not None:
        return io.BytesIO(pdf_data)
    else:
        raise ValueError('Either pdf_path or pdf_data must be provided')


def get_pages(pdf, pages):
    if pages is not None:
        return list(pages)
    else:
        return list(range(1, len(pdf.pages) + 1))


def create_target_dir():
    random_folder_name = str(uuid.uuid4())
    base_dir = os.path.join(main_directory, 'server/api/endpoints/skills/pdf_editor/temp_data/')
    os.makedirs(base_dir, exist_ok=True)
    target_dir = os.path.join(base_dir, random_folder_name)
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def screenshot_pages(
        pdf_path: str=None,
        pdf_data: bytes=None,
        max_length_px: int = 1500,
        pages: list=None
    ) -> List[str]:

    with get_pdf_file(pdf_path, pdf_data) as pdf_file:
        pdf = PdfReader(pdf_file)
        pages = get_pages(pdf, pages)
        target_dir = create_target_dir()

        pdf_file.seek(0)
        images = convert_from_bytes(pdf_file.read())
        image_paths = []

        for page_num in pages:
            for i, image in enumerate(images[page_num-1:page_num]):
                image_path = os.path.join(target_dir, f'page_{page_num}_{i}.png')
                if max(image.size) > max_length_px:
                    image.thumbnail((max_length_px, max_length_px))
                image.save(image_path, 'PNG')
                image_paths.append(image_path)

    return image_paths


if __name__ == '__main__':
    pdf_path = 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
    images = screenshot_pages(pdf_path=pdf_path,max_length_px=1000)
    print(images)