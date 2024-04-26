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

from typing import List, Optional
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.validation.validate_file_access import validate_file_access
from server.api.validation.validate_mate_username import validate_mate_username
from server.api.validation.validate_skills import validate_skills
from server.api.endpoints.mates.get_mate import get_mate_processing
