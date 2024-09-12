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

from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from server.api.endpoints.skills.files.providers.openmates.delete import delete as openmates_delete
from server.api.models.skills.files.skills_files_delete import FilesDeleteOutput


async def delete(
    provider: str,
    file_path: str
) -> FilesDeleteOutput:
    """
    Delete a file from a provider
    """
    add_to_log(module_name="OpenMates | API | Files | Delete", state="start", color="yellow", hide_variables=True)

    if provider == "dropbox":
        # return await dropbox_delete(file_path)
        # TODO: implement dropbox delete
        pass
    else:
        file_id = file_path.split("/")[-2]
        return await openmates_delete(
            file_id=file_id
        )