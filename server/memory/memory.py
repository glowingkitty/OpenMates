import os
from redis import Redis
import json

# Reuse the redis_url from celery.py
redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"


default_expiration_time = 86400 # 24 hours


########################################################
# Users
########################################################

# Save/Get one

def save_user_to_memory(user_id, user_data):
    """
    Save a user to Redis (Dragonfly) by user ID.
    """
    client = Redis.from_url(redis_url)
    client.set(f"user:{user_id}", json.dumps(user_data), ex=default_expiration_time)

def get_user_from_memory(user_id):
    """
    Retrieve a user from Redis (Dragonfly) by user ID.
    """
    client = Redis.from_url(redis_url)
    user_data = client.get(f"user:{user_id}")
    if user_data:
        return json.loads(user_data)
    return None


########################################################
# Teams
########################################################

# Save/Get one

def save_team_to_memory(team_id, team_data):
    """
    Save a team to Redis (Dragonfly) by team ID.
    """
    client = Redis.from_url(redis_url)
    client.set(f"team:{team_id}", json.dumps(team_data), ex=default_expiration_time)

def get_team_from_memory(team_id):
    """
    Retrieve a team from Redis (Dragonfly) by team ID.
    """
    client = Redis.from_url(redis_url)
    team_data = client.get(f"team:{team_id}")
    if team_data:
        return json.loads(team_data)
    return None


# Save/Get by discord guild id

def save_team_slug_with_discord_guild_id_to_memory(guild_id, team_slug):
    """
    Save a team slug to Redis (Dragonfly) with its discord guild id, and no other data
    """
    client = Redis.from_url(redis_url)
    client.set(f"team:guild_id:{guild_id}", team_slug, ex=default_expiration_time)

def get_team_slug_with_discord_guild_id_from_memory(guild_id):
    """
    Retrieve a team slug from Redis (Dragonfly) by guild ID.
    """
    client = Redis.from_url(redis_url)
    team_slug = client.get(f"team:guild_id:{guild_id}")
    if team_slug:
        return team_slug
    return None


# Save/Get all

def save_teams_to_memory(teams):
    """
    Save teams to Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    client.set("teams", json.dumps(teams), ex=default_expiration_time)

def get_teams_from_memory():
    """
    Retrieve all teams from Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    teams_data = client.get("teams")
    if teams_data:
        return json.loads(teams_data)
    return None


########################################################
# Tasks
########################################################

# Save/Get one

def save_task_to_memory(task_id, task_data):
    """
    Save a task to Redis (Dragonfly) by task ID.
    """
    client = Redis.from_url(redis_url)
    client.set(f"task:{task_id}", json.dumps(task_data), ex=300)  # Expire after 5 minutes

def get_task_from_memory(task_id):
    """
    Retrieve a task from Redis (Dragonfly) by task ID.
    """
    client = Redis.from_url(redis_url)
    task_data = client.get(f"task:{task_id}")
    if task_data:
        return json.loads(task_data)
    return None