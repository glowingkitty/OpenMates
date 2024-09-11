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


from typing import List, Dict, Any
from fastapi import HTTPException
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from server.api.endpoints.skills.files.upload import upload
from server.api.endpoints.skills.ai.ask import ask as ask_ai
from datetime import datetime, timedelta
import uuid



async def translate(
    team_slug: str,
    api_token: str,
    title: str,
    epub_bytes: bytes,
    output_language: str
) -> FilesUploadOutput:

    # TODO processing

    file_name = f"{title.lower().replace(' ', '_')}.epub"
    file_id = uuid.uuid4().hex[:10]
    expiration_datetime = datetime.now() + timedelta(days=1)
    file_info = await upload(
        provider="books",
        team_slug=team_slug,
        file_path=f"books/{file_id}/{file_name}",
        name=file_name,
        file_data=translated_epub_bytes,
        file_id=file_id,
        encryption_key=api_token+file_id,
        expiration_datetime=expiration_datetime.isoformat(),
        access_public=False
    )

    return file_info