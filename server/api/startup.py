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
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


from server.api.memory import get_all_users_from_memory, load_users_into_memory, get_user_from_memory
from server.api.endpoints.skills.messages.providers.discord.receive import start_discord_listener
from server.api.endpoints.tasks.tasks import ask_mate_task

async def api_startup():
    # Startup event
    logger.info("Processing startup events...")

    logger.info("Loading users into memory...")
    # load_users_into_memory()

    # Check which users have a Discord connection and start an instance to check for new messages
    logger.info("Start listening for Discord messages for users with a Discord connection...")
    # users = get_all_users_from_memory()
    server_url_to_users = {}
    server_url_to_token = {}

    # TODO lets simplify testing
    # 1. load user data from strapi into memory and print it out
    # 2. update database model to include discord server data in user model
    # 3. then implement the logic to start the discord listener for each user

    # for user_key in users:
    #     user_id = user_key.decode('utf-8').split(':')[1]
    #     user = get_user_from_memory(user_id)
    #     if user and user.get('has_discord_connection'):
    #         server_url = user.get('discord_server_url')
    #         if server_url:
    #             if server_url not in server_url_to_users:
    #                 server_url_to_users[server_url] = set()
    #                 server_url_to_token[server_url] = user['discord_bot_token']
    #             server_url_to_users[server_url].add(user_id)

    # for server_url, user_ids in server_url_to_users.items():
    #     bot_token = server_url_to_token[server_url]
    #     # TODO add a function that extracts the team slug, and the mate at which the message is directed to, from the message and user data
    #     asyncio.create_task(start_discord_listener(
    #         bot_token=bot_token, 
    #         message_handler=lambda m: [ask_mate_task.delay(
    #             team_slug=server_url,
    #             message=m.content,
    #             mate_username=m.mate_username,
    #             task_info=m.task_info
    #         ) for uid in user_ids]
    #     ))

    logger.info("API startup complete.")