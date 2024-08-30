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
from server.api.models.skills.docs.skills_create import DocsCreateOutput


async def create(
    title: str,
    elements: List[dict]
) -> DocsCreateOutput:
    """
    Create a new document
    """
    add_to_log(module_name="OpenMates | API | Create document", state="start", color="yellow", hide_variables=True)
    add_to_log("Creating a new document ...")


    return DocsCreateOutput(
        title=title,
        file_url="",
        expiration_date_time="2025-01-01T00:00:00Z"
    )