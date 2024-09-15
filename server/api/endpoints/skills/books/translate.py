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
from bs4 import BeautifulSoup

def example_translate(input_text: str, output_language: str) -> str:
    return f"Here would be the translation of '{input_text}' to {output_language}"

async def translate(
    team_slug: str,
    api_token: str,
    ebook_data: bytes,
    output_language: str
) -> FilesUploadOutput:

    # Save the bytes to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as temp_file:
        temp_file.write(ebook_data)
        temp_file_path = temp_file.name

    try:
        # Load the epub file
        book = epub.read_epub(temp_file_path)

        # Translate the title
        title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Untitled"
        translated_title = example_translate(title, output_language)
        book.set_title(translated_title)

        # Translate the text content
        for item in book.get_items():
            if item.get_type() == epub.EpubHtml:
                soup = BeautifulSoup(item.get_body_content(), 'html.parser')
                for paragraph in soup.find_all('p'):
                    translated_text = example_translate(paragraph.get_text(), output_language)
                    paragraph.string.replace_with(translated_text)
                item.set_content(str(soup))

        # Save the translated epub to a new file
        translated_epub_path = tempfile.mktemp(suffix=".epub")
        epub.write_epub(translated_epub_path, book)

        with open(translated_epub_path, 'rb') as f:
            translated_epub_data = f.read()

    except Exception as e:
        add_to_log(f"Error translating ebook: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred while translating the ebook")
    finally:
        os.remove(temp_file_path)  # Clean up the temporary file
        if os.path.exists(translated_epub_path):
            os.remove(translated_epub_path)

    expiration_datetime = datetime.now() + timedelta(days=1)
    file_info = await upload(
        team_slug=team_slug,
        api_token=api_token,
        provider="books",
        file_name=f"{quote(translated_title)}.epub",
        file_data=translated_epub_data,
        expiration_datetime=expiration_datetime.isoformat(),
        access_public=False,
        folder_path="books"
    )

    return file_info