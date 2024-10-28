import logging
import os
import redis.asyncio as redis
from server.server_config import get_server_config
from server.api.endpoints.users.check_for_admin_user import check_for_admin_user
from server.api.endpoints.users.create_server_admin_user import create_server_admin_user
from server.api.models.users.users_create import UsersCreateInput
import requests
import sys
import time
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

cms_url = f"http://cms:{os.getenv('CMS_PORT')}"
redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"
redis_client = redis.Redis.from_url(redis_url)

def is_cms_online():
    """
    Check if the Strapi CMS is online and accessible.
    """
    try:
        response = requests.get(f"{cms_url}/_health")
        return response.status_code == 204
    except requests.RequestException:
        return False


async def check_for_admin():
    # wait for Strapi to be ready
    logger.info("Waiting for Strapi CMS to come online...")

    attempts = 0
    max_attempts = 30

    while not is_cms_online():
        attempts += 1
        if attempts > max_attempts:
            logger.error(f"CMS not online after {max_attempts} attempts. Exiting with error.")
            sys.exit(1)
        logger.debug(f"CMS not yet online. Attempt {attempts}/{max_attempts}. Retrying in 5 seconds...")
        time.sleep(5)

    # make request to strapi to check if any user with server admin rights exists
    if await check_for_admin_user() == False:
        # create a new user with server admin rights
        logger.info("No OpenMates server admin user found. Creating one...")
        await create_server_admin_user(
            input=UsersCreateInput(
                username=os.getenv("DEFAULT_ADMIN_USERNAME"),
                email=os.getenv("DEFAULT_ADMIN_EMAIL"),
                password=os.getenv("DEFAULT_ADMIN_PASSWORD"),
            ),
            team_name=os.getenv("DEFAULT_ADMIN_TEAM_NAME")
        )


async def clear_all_memory():
    """
    Clear all data from Redis (Dragonfly).
    """
    logger.info("Clearing all data from memory...")
    await redis_client.flushall()
    logger.info("Cleared all data from memory")


async def api_startup():
    # server_config already checks if all config files are present

    logger.info("Processing startup events...")

    await clear_all_memory()

    # get server config
    server_config = get_server_config()

    # # TODO check if the apps exist in strapi, if not create them (based on server/configs/apps/apps.yml - check each app, make sure the app is allowed and if so, it is in strapi)
    # await check_for_apps()

    # TODO check if the skills exist in strapi, if not create them
    # await check_for_skills()

    # TODO check if the focuses exist in strapi, if not create them
    # await check_for_focuses()

    # # TODO check if the mates exist in strapi, if not create them
    # await check_for_mates()

    # # TODO if no user with server admin rights exists:
    # if DEFAULT_ADMIN_USERNAME and DEFAULT_ADMIN_PASSWORD are set, create the user. Else, show in log and ask user to create one via the webapp
    await check_for_admin()

    logger.info("API startup complete.")