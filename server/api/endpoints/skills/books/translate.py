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
        # load the epub file and get the title, to based on that create the epub file name
        book = epub.read_epub(temp_file_path)

        title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Untitled"
        file_name = f"{quote(title)}.epub"

        translated_epub_data = ebook_data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid EPUB file: {str(e)}")
    finally:
        os.remove(temp_file_path)  # Clean up the temporary file


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