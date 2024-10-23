import logging
import os
import redis.asyncio as redis
from server.server_config import get_server_config
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"
redis_client = redis.Redis.from_url(redis_url)

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

    # # TODO if no user with server admin rights exists, show in log and ask user to create one via the webapp
    # await check_for_admin()

    logger.info("API startup complete.")