import os
import logging
import sys
import yaml
from redis import Redis
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')
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

def save_server_config_to_memory(config: dict) -> bool:
    """
    Save the server configuration to Redis (Dragonfly).
    """
    logger.debug("Saving server configuration to memory")
    client = Redis.from_url(redis_url)
    client.set("server_config", json.dumps(config))
    logger.info("Server configuration saved to memory")
    return True

def get_server_config_from_memory() -> dict:
    """
    Retrieve the server configuration from Redis (Dragonfly).
    """
    logger.debug("Getting server configuration from memory")
    client = Redis.from_url(redis_url)
    config = client.get("server_config")
    if config:
        logger.info("Server configuration retrieved from memory")
        return json.loads(config)
    logger.info("Failed to get server configuration from memory")
    return None

def load_yaml_file(file_path: str) -> dict:
    """
    Load a YAML file and return its content as a dictionary.
    """
    # Construct the full path based on the script's directory
    full_path = os.path.join(script_dir, file_path.lstrip('/'))
    try:
        with open(full_path, 'r') as file:
            content = yaml.safe_load(file)
            logger.info(f"Loaded YAML file: {full_path}")
            return content
    except FileNotFoundError:
        logger.error(f"YAML file not found: {full_path}")
        return None
    except yaml.YAMLError as exc:
        logger.error(f"Error parsing YAML file {full_path}: {exc}")
        return None

def replace_file_paths_with_content(config: dict) -> dict:
    """
    Recursively replace file paths ending with .yml or .yaml in the config dictionary
    with the content of those YAML files, including nested files.
    """
    def process_value(value):
        if isinstance(value, str) and (value.endswith('.yml') or value.endswith('.yaml')):
            # Load the YAML file and replace the path with its content
            file_content = load_yaml_file(value)
            if file_content is not None:
                # Recursively process the loaded content
                return replace_file_paths_with_content(file_content)
            return value
        elif isinstance(value, dict):
            # Recursively process nested dictionaries
            return replace_file_paths_with_content(value)
        elif isinstance(value, list):
            # If the value is a list, iterate through each item
            return [process_value(item) for item in value]
        return value

    return {key: process_value(value) for key, value in config.items()}

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
            logger.debug(f"Processed configuration: {json.dumps(config, indent=2)}")
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

    # If loading from memory fails, load from YAML and save to memory
    if not server_config:
        logger.info("Loading server configuration from YAML file...")
        server_config = load_server_config()
        if server_config:
            save_server_config_to_memory(server_config)
        else:
            logger.error("Failed to load server configuration.")
            sys.exit(1)
