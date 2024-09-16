################
# Default Imports
################
import sys
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import tempfile
import asyncio

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
from server.api.endpoints.skills.ai.ask import ask
from datetime import datetime, timedelta
from ebooklib import epub
from urllib.parse import quote
import tempfile
import json


async def translate_text(
        user_api_token: str,
        team_slug: str,
        text: str, 
        output_language: str
) -> str:
    response = await ask(
        user_api_token=user_api_token,
        team_slug=team_slug,
        system=f"You are an expert translator. Translate the given text to {output_language} and output nothing else except the translation output.",
        message=text,
        provider={ "name": "chatgpt","model": "gpt-4o-mini" },
        temperature=0.5
    )
    if type(response) != dict:
        add_to_log(type(response))
        add_to_log(response)
    translated_text = response["content"][0]["text"]
    return translated_text


async def translate_xhtml_file(
        user_api_token: str,
        team_slug: str,
        file_path: str,
        output_language: str
):
    ET.register_namespace('', "http://www.w3.org/1999/xhtml")
    tree = ET.parse(file_path)
    root = tree.getroot()

    async def translate_element(elem):
        if elem.text and elem.text.strip():
            elem.text = await translate_text(
                user_api_token=user_api_token,
                team_slug=team_slug,
                text=elem.text,
                output_language=output_language
            )
        if elem.tail and elem.tail.strip():
            elem.tail = await translate_text(
                user_api_token=user_api_token,
                team_slug=team_slug,
                text=elem.tail,
                output_language=output_language
            )

    tasks = [translate_element(elem) for elem in root.iter()]
    await asyncio.gather(*tasks)

    tree.write(file_path, encoding='utf-8', xml_declaration=True)


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
                    await translate_xhtml_file(
                        user_api_token=api_token,
                        team_slug=team_slug,
                        file_path=file_path,
                        output_language=output_language
                    )

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
        file_name = f"{quote(title)}_translated_{output_language}.epub"

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