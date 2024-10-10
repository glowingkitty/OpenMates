import logging
import os
import redis.asyncio as redis

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
    # server_config_check already checks if all config files are present

    logger.info("Processing startup events...")

    await clear_all_memory()

    # TODO check if an admin user exists in strapi, if not create it
    await check_admin()

    # TODO check if the apps exist in strapi, if not create them (based on server/configs/apps/ - check each folder for an app.yml file and for every app.yml file, make sure the app is in strapi)
    await check_apps()

    # TODO check if the mates exist in strapi, if not create them
    await check_mates()

    # TODO if no teams exist, show in log and ask user to create one via the webapp
    await check_teams()

    logger.info("API startup complete.")