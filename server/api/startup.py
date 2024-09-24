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
    await redis_client.flushall()
    logger.info("Cleared all data from memory")


async def api_startup():
    # Existing startup code
    logger.info("Processing startup events...")

    await clear_all_memory()

    # TODO not needed to load all into memory! only load team into memory once a request from team is made (like with users), else request data from cms

    # TODO lets simplify testing
    # 2. update database model to include discord server data in user model
    # 3. then implement the logic to start the discord listener for each user
    # 4. test / implement webhooks to receive messages from slack, mattermost, etc.

    logger.info("Check if all bots have defined invite links in the database, else create them...")

    # Check which users have a Discord connection and start an instance to check for new messages
    logger.info("Start listening for Discord messages for users with a Discord connection...")

    logger.info("API startup complete.")