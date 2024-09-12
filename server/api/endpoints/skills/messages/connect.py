################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from typing import List
from server.api.models.skills.messages.skills_connect_server import MessagesConnectOutput


async def connect(
    team_name: str,
    include_all_mates: bool,
    mates: List[str]
) -> MessagesConnectOutput:
    """
    Gather all invite links for the given bots and return them
    """
    # TODO load on startup of software all mates and their invite links from strapi
    pass