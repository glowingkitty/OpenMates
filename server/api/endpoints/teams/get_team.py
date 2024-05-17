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

from server.cms.strapi_requests import make_strapi_request, get_nested
from typing import Dict, Union, Literal
from fastapi.responses import JSONResponse
from fastapi import HTTPException

async def get_team(
    team_slug: str,
    output_raw_data: bool = False,
    output_format: Literal["JSONResponse", "dict"] = "JSONResponse"
) -> Union[JSONResponse, Dict, HTTPException]:
    """
    Get a specific team.
    """
    