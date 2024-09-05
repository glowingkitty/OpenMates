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

from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from server.api.endpoints.skills.files.providers.openmates.upload import upload as openmates_upload
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput


async def upload(
    provider: str,
    file_path: str,
    name: str,
    content_base64: str
) -> FilesUploadOutput:
    """
    Upload a file to a provider
    """
    add_to_log(module_name="OpenMates | API | Files | Upload", state="start", color="yellow", hide_variables=True)

    if provider == "dropbox":
        # return await dropbox_upload(file_path)
        # TODO: implement dropbox upload
        pass
    else:
        return await openmates_upload(
            provider=provider,
            file_path=file_path,
            name=name,
            content_base64=content_base64
        )