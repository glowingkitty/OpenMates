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

import os
from redis import Redis
import json

# Reuse the redis_url from celery.py
redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"

def load_users_from_disk():
    """
    Load users from Strapi. This is a placeholder function and should be implemented
    to fetch user data from your Strapi instance.
    """
    # Placeholder implementation
    # Replace this with actual code to fetch users from Strapi
    users = [
        {"id": 1, "name": "Alice", "has_discord_connection": True, "discord_bot_token": "token1"},
        {"id": 2, "name": "Bob", "has_discord_connection": False, "discord_bot_token": None},
    ]
    return users

def store_users_in_memory(client, users):
    """
    Store users in Redis (Dragonfly).
    """
    for user in users:
        client.set(f"user:{user['id']}", json.dumps(user))

def load_users_into_memory():
    """
    Load users from Strapi and store them in Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    users = load_users_from_disk()
    store_users_in_memory(client, users)

def get_all_users_from_memory():
    """
    Retrieve all users from Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    users = client.keys("user:*")
    return users

def get_user_from_memory(user_id):
    """
    Retrieve a user from Redis (Dragonfly) by user ID.
    """
    client = Redis.from_url(redis_url)
    user_data = client.get(f"user:{user_id}")
    if user_data:
        return json.loads(user_data)
    return None