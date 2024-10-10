import os
import logging
import sys
import yaml
from redis import Redis
import json
import re

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:     %(message)s')
logger = logging.getLogger(__name__)

# Reuse the redis_url from memory.py
redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"

# Check if the server.yml file exists
script_dir = os.path.dirname(__file__)
yaml_path = os.path.join(script_dir, "server.yml")
env_path = os.path.join(script_dir.split("/server")[0], ".env")

logger.info(f"server.yml path: {yaml_path}")
logger.info(f".env path: {env_path}")

# List of required environment variables
required_env_variables = [
    "SERVER_HOST", "CMS_PORT", "CMS_TOKEN", "API_TOKEN_SALT",
    "APP_KEYS", "ADMIN_JWT_SECRET", "TRANSFER_TOKEN_SALT",
    "NODE_ENV", "DATABASE_CLIENT", "DATABASE_NAME",
    "DATABASE_FILENAME", "DATABASE_USERNAME", "DATABASE_PASSWORD",
    "JWT_SECRET", "IN_MEMORY_DATABASE_PORT", "WEB_BROWSER_SECRET_KEY",
    "WEB_BROWSER_PORT", "REST_API_PORT"
]

# TODO replace every {fieldname} in the markdown files with the actual fieldname from the yaml file (on the same level)
# TODO save file_cache in redis (?)
# TODO is client.set the best method to save the whole config while still being able to retrieve individual sub values instead of loading the whole thing?

# Add a new global variable to store cached file contents
file_cache = {}

def save_server_config_to_memory(config: dict) -> bool:
    """
    Save the server configuration to Redis (Dragonfly) using hash.
    """
    logger.debug("Saving server configuration to memory")
    client = Redis.from_url(redis_url)

    # Convert all values to strings
    string_config = {k: json.dumps(v) for k, v in config.items()}

    # Use HSET to store the configuration as a hash
    client.hset("server_config", mapping=string_config)

    logger.info("Server configuration saved to memory")
    return True

def get_server_config_from_memory() -> dict:
    """
    Retrieve the server configuration from Redis (Dragonfly) using hash.
    """
    logger.debug("Getting server configuration from memory")
    client = Redis.from_url(redis_url)

    # Use HGETALL to retrieve the entire hash
    config = client.hgetall("server_config")

    if config:
        # Convert the values back from strings to their original types
        parsed_config = {k.decode(): json.loads(v.decode()) for k, v in config.items()}
        logger.info("Server configuration retrieved from memory")
        return parsed_config

    logger.info("Failed to get server configuration from memory")
    return None

def load_yaml_file(file_path: str) -> dict:
    """
    Load a YAML file and return its content as a dictionary.
    Uses a cache to avoid loading the same file multiple times.
    """
    # Construct the full path based on the script's directory
    full_path = os.path.join(script_dir, file_path.lstrip('/'))

    # Check if the file content is already in the cache
    if full_path in file_cache:
        logger.debug(f"Retrieved cached content for: {full_path}")
        return file_cache[full_path]

    try:
        with open(full_path, 'r') as file:
            content = yaml.safe_load(file)
            logger.info(f"Loaded YAML file: {full_path}")
            # Cache the content
            file_cache[full_path] = content
            return content
    except FileNotFoundError:
        logger.error(f"YAML file not found: {full_path}")
        return None
    except yaml.YAMLError as exc:
        logger.error(f"Error parsing YAML file {full_path}: {exc}")
        return None

def replace_file_paths_with_content(config):
    """
    Recursively replace file paths ending with .yml, .yaml, or .md in the config dictionary
    with the content of those files, including nested files.
    """
    # logger.debug(f"Processing config")

    def process_value(value):
        if isinstance(value, str):
            if value.endswith(('.yml', '.yaml')):
                # Load the YAML file and replace the path with its content
                file_content = load_yaml_file(value)
                if file_content is not None:
                    # Recursively process the loaded content
                    return replace_file_paths_with_content(file_content)
            elif value.endswith('.md'):
                # Load the MD file and return its content as a string
                return load_md_file(value)
            return value
        elif isinstance(value, dict):
            # Recursively process nested dictionaries
            return replace_file_paths_with_content(value)
        elif isinstance(value, list):
            # If the value is a list, iterate through each item
            return [process_value(item) for item in value]
        return value

    if isinstance(config, dict):
        return {key: process_value(value) for key, value in config.items()}
    elif isinstance(config, str):
        # If the input is a string (e.g., MD file content), return it as is
        return config
    else:
        logger.warning(f"Unexpected config type: {type(config)}")
        return config

def load_md_file(file_path: str) -> str:
    """
    Load an MD file and return its content as a string.
    Uses a cache to avoid loading the same file multiple times.
    """
    # Construct the full path based on the script's directory
    full_path = os.path.join(script_dir, file_path.lstrip('/'))

    # Check if the file content is already in the cache
    if full_path in file_cache:
        logger.debug(f"Retrieved cached content for: {full_path}")
        return file_cache[full_path]

    try:
        with open(full_path, 'r') as file:
            content = file.read()
            logger.info(f"Loaded MD file: {full_path}")
            # Cache the content
            file_cache[full_path] = content
            return content
    except FileNotFoundError:
        logger.error(f"MD file not found: {full_path}")
        return None
    except Exception as exc:
        logger.error(f"Error reading MD file {full_path}: {exc}")
        return None

def load_server_config():
    """
    Load server configuration from a YAML file into memory.
    """
    try:
        with open(yaml_path, 'r') as file:
            config = yaml.safe_load(file)
            logger.info("Configuration loaded successfully.")
            # Replace file paths with their content
            config = replace_file_paths_with_content(config)
            logger.debug(f"Processed configuration.")
            return config
    except FileNotFoundError:
        logger.error("Configuration file not found.")
        return None
    except yaml.YAMLError as exc:
        logger.error(f"Error parsing YAML file: {exc}")
        return None

def check_env_variables():
    """
    Check if all required environment variables are set.
    Log missing variables and return a boolean indicating if all variables are present.
    """
    missing_vars = []

    # Iterate through the list of required variables
    for var in required_env_variables:
        if not os.getenv(var):
            missing_vars.append(var)

    # Log the results
    if missing_vars:
        # Construct a single log message with spacing and each missing variable on a new line
        missing_vars_message = "The following environment variables are missing in the /.env file:\n\n" + \
                               "\n".join(f"  - {var}" for var in missing_vars) + "\n"

        # Log the entire message at once
        logger.info(missing_vars_message)
        return False
    else:
        logger.info("All required environment variables are set.")
        return True

def save_file_cache_to_redis():
    """
    Save the file_cache to Redis.
    """
    logger.debug("Saving file_cache to Redis")
    client = Redis.from_url(redis_url)
    client.set("file_cache", json.dumps(file_cache))
    logger.info("file_cache saved to Redis")

def load_file_cache_from_redis():
    """
    Load the file_cache from Redis.
    """
    logger.debug("Loading file_cache from Redis")
    client = Redis.from_url(redis_url)
    cached_data = client.get("file_cache")
    if cached_data:
        global file_cache
        file_cache = json.loads(cached_data)
        logger.info("file_cache loaded from Redis")
    else:
        logger.info("No file_cache found in Redis")

if __name__ == "__main__":
    if not os.path.exists(yaml_path):
        logger.error("Configuration file server.yml not found.")
        sys.exit(1)

    # Run the environment variable check
    logger.info("Starting environment variable check...")
    all_vars_present = check_env_variables()

    # If any environment variables are missing, exit
    if not all_vars_present:
        logger.info("Closing REST API server due to missing environment variables...")
        sys.exit(1)

    # Attempt to load the server configuration from memory
    logger.info("Attempting to load server configuration from memory...")
    server_config = get_server_config_from_memory()

    # Load file_cache from Redis
    load_file_cache_from_redis()

    # If loading from memory fails, load from YAML and save to memory
    if not server_config:
        logger.info("Loading server configuration from YAML file...")
        server_config = load_server_config()
        logger.info(f"Server configuration loaded from YAML file")
        if server_config:
            # Save the updated configuration to memory
            save_server_config_to_memory(server_config)

            # Save file_cache to Redis
            save_file_cache_to_redis()
        else:
            logger.error("Failed to load server configuration.")
            sys.exit(1)
