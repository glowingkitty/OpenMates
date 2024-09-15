################
# Default Imports
################
import sys
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import tempfile

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################


from typing import List, Dict, Any
from fastapi import HTTPException
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from server.api.endpoints.skills.files.upload import upload
from server.api.endpoints.skills.ai.ask import ask as ask_ai
from datetime import datetime, timedelta
from ebooklib import epub
from urllib.parse import quote
import tempfile

def example_translate(text: str, output_language: str) -> str:
    # This is a placeholder function. Replace with actual translation logic.
    return f"Translated: '{text}' to '{output_language}'"

async def translate(
    team_slug: str,
    api_token: str,
    ebook_data: bytes,
    output_language: str
) -> FilesUploadOutput:

    # Create a temporary directory to work with the EPUB
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save the input EPUB to a temporary file
        input_epub = os.path.join(temp_dir, "input.epub")
        with open(input_epub, "wb") as f:
            f.write(ebook_data)

        # Extract the EPUB file
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(input_epub, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Find and process all XHTML files
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith('.xhtml') or file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    translate_xhtml_file(file_path, output_language)

        # Create a new EPUB file with translated content
        output_epub = os.path.join(temp_dir, "output.epub")
        with zipfile.ZipFile(output_epub, 'w') as zip_ref:
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, extract_dir)
                    zip_ref.write(file_path, arcname)

        # Read the translated EPUB data
        with open(output_epub, "rb") as f:
            translated_epub_data = f.read()

        # Get the book title for the file name
        book = epub.read_epub(input_epub)
        title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Untitled"
        file_name = f"{quote(title)}_translated.epub"

    # Upload the translated EPUB
    expiration_datetime = datetime.now() + timedelta(days=1)
    file_info = await upload(
        team_slug=team_slug,
        api_token=api_token,
        provider="books",
        file_name=file_name,
        file_data=translated_epub_data,
        expiration_datetime=expiration_datetime.isoformat(),
        access_public=False,
        folder_path="books"
    )

    return file_info

def translate_xhtml_file(file_path, output_language):
    ET.register_namespace('', "http://www.w3.org/1999/xhtml")
    tree = ET.parse(file_path)
    root = tree.getroot()

    for elem in root.iter():
        if elem.text and elem.text.strip():
            elem.text = example_translate(elem.text, output_language)
        if elem.tail and elem.tail.strip():
            elem.tail = example_translate(elem.tail, output_language)

    tree.write(file_path, encoding='utf-8', xml_declaration=True)