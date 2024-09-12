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

from server.api import *
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
    # TODO if phase 1: return all invite links for all mates
    # TODO if phase 2: create MessengerTeam entry, connect it with team and this way request from a team can be matched with the right team
    pass