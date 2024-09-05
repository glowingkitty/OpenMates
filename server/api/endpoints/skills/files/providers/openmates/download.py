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
from server.cms.strapi_requests import get_strapi_upload


async def download(
    provider: str,
    file_path: str
) -> StreamingResponse:
    """
    Download a file from the OpenMates server
    """
    add_to_log(module_name="OpenMates | API | Files | Providers | OpenMates | Download", state="start", color="yellow", hide_variables=True)
    add_to_log(f"Downloading file from OpenMates server ...")
    return await get_strapi_upload(f"{provider}/{file_path}")