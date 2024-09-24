import os
import logging
import redis.asyncio as redis

logger = logging.getLogger(__name__)

redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"
redis_client = redis.Redis.from_url(redis_url)

async def api_shutdown():
    logger.info("Processing shutdown events...")

    try:
        logger.info("Closing Redis connection...")
        await redis_client.close()
        logger.info("Redis connection closed successfully.")
    except Exception as e:
        logger.error(f"Error closing Redis connection: {e}")

    logger.info("Shutdown complete.")