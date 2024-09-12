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

import logging
import asyncio

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


from server.api.endpoints.tasks.tasks import ask_mate_task

async def api_startup():
    # Startup event
    logger.info("Processing startup events...")

    # TODO lets simplify testing
    # 2. update database model to include discord server data in user model
    # 3. then implement the logic to start the discord listener for each user
    # 4. test / implement webhooks to receive messages from slack, mattermost, etc.

    logger.info("Check if all bots have defined invite links in the database, else create them...")

    # Check which users have a Discord connection and start an instance to check for new messages
    logger.info("Start listening for Discord messages for users with a Discord connection...")

    logger.info("API startup complete.")