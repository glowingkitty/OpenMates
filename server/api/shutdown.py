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
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"
redis_client = redis.Redis.from_url(redis_url)

async def api_shutdown():
    logger.info("Processing shutdown events...")

    try:
        await redis_client.close()
        logger.info("Redis connection closed successfully.")
    except Exception as e:
        logger.error(f"Error closing Redis connection: {e}")

    logger.info("Shutdown complete.")