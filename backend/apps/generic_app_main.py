# backend/apps/generic_app_main.py
# Generic application runner for apps using the unified Dockerfile.base.
# This script instantiates BaseApp and exposes its FastAPI instance for Uvicorn.

import os
import logging
from apps.base_app import BaseApp # Available at /app/apps/base_app.py

# Basic logging setup for the runner itself
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

app_instance = None
app = None

try:
    APP_NAME = os.getenv("APP_NAME")
    if not APP_NAME:
        logger.error("APP_NAME environment variable is not set. Cannot start application.")
        raise ValueError("APP_NAME environment variable must be set.")

    # Construct the app-specific port environment variable name
    # e.g., if APP_NAME is "ai", it looks for "AI_APP_INTERNAL_PORT"
    # The CMD in Dockerfile.base will use a generic $APP_INTERNAL_PORT,
    # so docker-compose.yml must map the specific port var to APP_INTERNAL_PORT.
    # Or, this script could also try a generic "APP_INTERNAL_PORT".
    # For clarity, let's assume docker-compose sets APP_INTERNAL_PORT directly for the CMD,
    # and this script reads the specific one for BaseApp instantiation.
    # If BaseApp needs the port, it should get it from its own env var.
    # The Uvicorn CMD uses ${APP_INTERNAL_PORT}.
    # BaseApp's __init__ takes app_port.

    app_specific_port_var = f"{APP_NAME.upper()}_APP_INTERNAL_PORT"
    APP_INTERNAL_PORT_STR = os.getenv(app_specific_port_var)

    if not APP_INTERNAL_PORT_STR:
        # Fallback to a generic APP_INTERNAL_PORT if the specific one isn't set
        APP_INTERNAL_PORT_STR = os.getenv("APP_INTERNAL_PORT")
        if not APP_INTERNAL_PORT_STR:
            logger.error(
                f"{app_specific_port_var} or APP_INTERNAL_PORT environment variable not set for app '{APP_NAME}'. "
                f"Defaulting to 8000, but this should be explicitly configured."
            )
            APP_INTERNAL_PORT_STR = "8000" # Default, but should be avoided by proper config
        else:
            logger.info(f"Using generic APP_INTERNAL_PORT: {APP_INTERNAL_PORT_STR} for app '{APP_NAME}'.")
    else:
        logger.info(f"Using specific {app_specific_port_var}: {APP_INTERNAL_PORT_STR} for app '{APP_NAME}'.")


    APP_PORT = int(APP_INTERNAL_PORT_STR)
    APP_DIR = f"/app/{APP_NAME}" # e.g., /app/ai, /app/travel

    logger.info(f"Initializing BaseApp for '{APP_NAME}' from directory '{APP_DIR}' on port '{APP_PORT}'.")

    # Instantiate BaseApp
    # BaseApp will load app.yml from APP_DIR/app.yml
    app_instance = BaseApp(app_dir=APP_DIR, app_port=APP_PORT)

    if app_instance and hasattr(app_instance, 'fastapi_app'):
        app = app_instance.fastapi_app # Expose the FastAPI app for Uvicorn
        logger.info(f"Successfully initialized and exposed FastAPI app for '{APP_NAME}'.")
    else:
        logger.error(f"Failed to initialize BaseApp or find fastapi_app for '{APP_NAME}'.")
        # This will likely cause Uvicorn to fail if 'app' is None.
        # Consider raising an exception or ensuring 'app' is a dummy FastAPI app on failure.
        from fastapi import FastAPI
        app = FastAPI(title=f"Error - {APP_NAME} Failed to Load", description="Application failed to initialize properly.")
        @app.get("/load-error")
        async def load_error():
            return {"error": f"Application {APP_NAME} could not be loaded."}

except Exception as e:
    logger.critical(f"Critical error during generic_app_main.py setup for APP_NAME='{os.getenv('APP_NAME', 'unknown')}': {e}", exc_info=True)
    # Ensure 'app' is defined even on critical failure so Uvicorn doesn't crash immediately,
    # though it will serve an error state.
    if app is None:
        from fastapi import FastAPI
        app = FastAPI(title="Critical Load Error", description="Application failed catastrophically during startup.")
        @app.get("/critical-load-error")
        async def critical_load_error():
            return {"error": "Application critical load failure."}