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

from typing import List

from server.api.endpoints.skills.docs.providers.microsoft_word.create import create as create_microsoft_word
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput

async def create(
    title: str,
    elements: List[dict]
) -> FilesUploadOutput:
    """
    Create a new document
    """
    add_to_log(module_name="OpenMates | API | Create document", state="start", color="yellow", hide_variables=True)
    add_to_log("Creating a new document ...")

    doc = await create_microsoft_word(title=title,elements=elements)

    return doc