import os
import logging
import sys
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')
logger = logging.getLogger(__name__)

# List of required environment variables
required_env_variables = [
    "HOST", "STRAPI_PORT", "STRAPI_TOKEN", "API_TOKEN_SALT",
    "APP_KEYS", "ADMIN_JWT_SECRET", "TRANSFER_TOKEN_SALT",
    "NODE_ENV", "DATABASE_CLIENT", "DATABASE_NAME",
    "DATABASE_FILENAME", "DATABASE_USERNAME", "DATABASE_PASSWORD",
    "JWT_SECRET", "DRAGONFLY_PORT", "WEB_BROWSER_SECRET_KEY",
    "WEB_BROWSER_PORT", "REST_API_PORT"
]

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
    # Run the environment variable check
    logger.info("Starting environment variable check...")
    all_vars_present = check_env_variables()

    # Log the final result
    if not all_vars_present:
        logger.info("Closing REST API server...")
        sys.exit(1)
