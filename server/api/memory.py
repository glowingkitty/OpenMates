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


def load_users_into_memory():
    """
    Load users from Strapi and store them in Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    users = users = [
        {"id": 1, "name": "Alice", "has_discord_connection": True, "discord_bot_token": "token1"},
        {"id": 2, "name": "Bob", "has_discord_connection": False, "discord_bot_token": None},
    ]
    for user in users:
        client.set(f"user:{user['id']}", json.dumps(user))



def load_data_into_memory():
    """
    Load data into memory (users, teams, mates, etc.)
    """
    load_users_into_memory()
    # load_teams_into_memory()
    # load_mates_into_memory()


def get_all_users():
    """
    Retrieve all users from Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    users = client.keys("user:*")
    return users

def get_user(user_id):
    """
    Retrieve a user from Redis (Dragonfly) by user ID.
    """
    client = Redis.from_url(redis_url)
    user_data = client.get(f"user:{user_id}")
    if user_data:
        return json.loads(user_data)
    return None