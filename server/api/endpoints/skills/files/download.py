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
from server.api.endpoints.skills.files.providers.openmates.download import download as openmates_download


async def download(
    provider: str,
    file_path: str
) -> StreamingResponse:
    """
    Download a file from a provider
    """
    add_to_log(module_name="OpenMates | API | Files | Download", state="start", color="yellow", hide_variables=True)

    if provider == "dropbox":
        # return await dropbox_download(file_path)
        # TODO: implement dropbox download
        pass
    else:
        return await openmates_download(provider=provider, file_path=file_path)