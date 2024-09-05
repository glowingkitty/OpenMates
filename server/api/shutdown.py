
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


import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def api_shutdown():
    logger.info("Processing shutdown events...")