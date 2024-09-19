import os
from redis import Redis
import json
from server.api.models.teams.teams_get_one import Team
from server.api.models.tasks.tasks_create import Task
from pydantic import BaseModel
from server.api.models.users.users_get_one import UserEncrypted
import logging

# Set up logger
logger = logging.getLogger(__name__)

# Reuse the redis_url from celery.py
redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"


default_expiration_time = 86400 # 24 hours


########################################################
# Users
########################################################

# Save/Get one

def save_user_to_memory(user_id: str, user_data: UserEncrypted) -> bool:
    """
    Save a user to Redis (Dragonfly) by user ID.
    """
    logger.debug(f"Saving user to memory")
    logger.debug(f"Saving user data: {user_data}")

    client = Redis.from_url(redis_url)
    user_data_dict = user_data.to_redis_dict()

    client.hmset(f"user:{user_id}", user_data_dict)
    client.expire(f"user:{user_id}", default_expiration_time)
    return True

def get_user_from_memory(user_id: str, fields: list[str] = None) -> UserEncrypted | None:
    """
    Retrieve a user from Redis (Dragonfly) by user ID.
    If fields are specified, return a User object with only those fields populated.
    """
    client = Redis.from_url(redis_url)
    user_key = f"user:{user_id}"

    # make sure id and username are in fields
    always_include_fields = ["id", "username", "api_token", 'is_server_admin', 'teams']
    if fields:
        fields = [x for x in fields if x not in always_include_fields]
        fields = always_include_fields + fields

    logger.debug(f"Getting user from memory with fields: {fields}")

    if fields:
        user_data = client.hmget(user_key, fields)
        if not any(user_data):
            return None
        return UserEncrypted.from_redis_dict({k: v for k, v in zip(fields, user_data) if v is not None})
    else:
        user_data = client.hgetall(user_key)
        if not user_data:
            return None
        return UserEncrypted.from_redis_dict({k.decode(): v.decode() for k, v in user_data.items()})


########################################################
# Teams
########################################################

# Save/Get one

def save_team_to_memory(team_id: str, team_data: Team) -> bool:
    """
    Save a team to Redis (Dragonfly) by team ID.
    """
    client = Redis.from_url(redis_url)
    client.set(f"team:{team_id}", json.dumps(team_data), ex=default_expiration_time)

    return True

def get_team_from_memory(team_id: str) -> Team:
    """
    Retrieve a team from Redis (Dragonfly) by team ID.
    """
    client = Redis.from_url(redis_url)
    team_data = client.get(f"team:{team_id}")
    if team_data:
        return Team(**json.loads(team_data))
    return None


# Save/Get by discord guild id

def save_team_slug_with_discord_guild_id_to_memory(guild_id: str, team_slug: str) -> bool:
    """
    Save a team slug to Redis (Dragonfly) with its discord guild id, and no other data
    """
    client = Redis.from_url(redis_url)
    client.set(f"team:guild_id:{guild_id}", team_slug, ex=default_expiration_time)

    return True

def get_team_slug_with_discord_guild_id_from_memory(guild_id: str) -> str:
    """
    Retrieve a team slug from Redis (Dragonfly) by guild ID.
    """
    client = Redis.from_url(redis_url)
    team_slug: str = client.get(f"team:guild_id:{guild_id}")
    if team_slug:
        return team_slug
    return None


# Save/Get all

def save_teams_to_memory(teams: list[Team]) -> bool:
    """
    Save teams to Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    client.set("teams", json.dumps(teams), ex=default_expiration_time)

    return True

def get_teams_from_memory() -> list[Team]:
    """
    Retrieve all teams from Redis (Dragonfly).
    """
    client = Redis.from_url(redis_url)
    teams_data = client.get("teams")
    if teams_data:
        return [Team(**team) for team in json.loads(teams_data)]
    return None


########################################################
# Tasks
########################################################

# Save/Get one

def save_task_to_memory(task_id: str, task_data: Task) -> bool:
    """
    Save a task to Redis (Dragonfly) by task ID.
    """
    client = Redis.from_url(redis_url)
    client.set(f"task:{task_id}", json.dumps(task_data), ex=300)  # Expire after 5 minutes

def get_task_from_memory(task_id: str) -> Task:
    """
    Retrieve a task from Redis (Dragonfly) by task ID.
    """
    client = Redis.from_url(redis_url)
    task_data = client.get(f"task:{task_id}")
    if task_data:
        return Task(**json.loads(task_data))
    return None