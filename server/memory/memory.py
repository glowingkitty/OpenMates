import os
from redis import Redis
import json

# Reuse the redis_url from celery.py
redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"


def get_user_from_memory(user_id):
    """
    Retrieve a user from Redis (Dragonfly) by user ID.
    """
    client = Redis.from_url(redis_url)
    user_data = client.get(f"user:{user_id}")
    if user_data:
        return json.loads(user_data)
    return None


def save_user_to_memory(user_id, user_data):
    """
    Save a user to Redis (Dragonfly) by user ID.
    """
    client = Redis.from_url(redis_url)
    client.set(f"user:{user_id}", json.dumps(user_data), ex=86400) # 24 hours expiration