import logging
import logging.config
import os
import sys
from pythonjsonlogger import jsonlogger
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Determine environment
SERVER_ENVIRONMENT = os.getenv("SERVER_ENVIRONMENT", "development").lower()
IS_PRODUCTION = SERVER_ENVIRONMENT == "production"

# Set default log level based on environment
DEFAULT_LOG_LEVEL = "WARNING" if IS_PRODUCTION else "INFO"
LOG_LEVEL = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs") # Adjust path relative to this file
API_LOG_PATH = os.path.join(LOGS_DIR, "api.log")
COMPLIANCE_LOG_PATH = os.path.join(LOGS_DIR, "compliance.log")

# Create logs directory if it doesn't exist
os.makedirs(LOGS_DIR, exist_ok=True)

# Create sensitive data filter instance
sensitive_filter = SensitiveDataFilter() # Keep the filter instance

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False, # Keep this False initially to avoid disabling logs unexpectedly
    "formatters": {
        "json": {
            # Use the standard jsonlogger formatter directly
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            "rename_fields": {
                "asctime": "timestamp",
                "levelname": "level"
                },
        },
        "compliance_json": {
                # Use the standard jsonlogger formatter directly
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(message)s", # Only the message for compliance
            },
            "simple": { # Keep a simple formatter for potential debugging if needed
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "filters": {
            "sensitive_data": {
                "()": SensitiveDataFilter, # Define the filter here
            },
            # Filter to apply only to specific handlers if needed
        "warning_and_above": {
            # This filter is intended to be used on handlers/loggers set to WARNING or higher
            # The level check happens at the handler/logger, not in the filter itself.
            "()": "logging.Filter",
            "name": "", # Match events attached to the root logger or specified logger name
            # Remove the 'level' key here
        },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": LOG_LEVEL,
                "formatter": "json",
                "filters": ["sensitive_data"], # Apply filter to handler
                "stream": sys.stdout, # Explicitly use stdout
            },
            "api_file": {
                "class": "logging.FileHandler",
                "level": "INFO", # Log INFO and above to file as per original main.py
                "formatter": "json",
                "filters": ["sensitive_data"], # Apply filter to handler
                "filename": API_LOG_PATH,
                "mode": "a",
                "encoding": "utf-8",
            },
            "compliance_file": {
                "class": "logging.FileHandler",
                "level": "INFO",
                "formatter": "compliance_json",
                "filters": ["sensitive_data"], # Apply filter to handler
                "filename": COMPLIANCE_LOG_PATH,
                "mode": "a",
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "app": { # Configure the base 'app' logger
                "handlers": ["console", "api_file"],
                "level": LOG_LEVEL,
                "propagate": False, # Prevent passing to root logger if handled here
            },
            "app.events": { # Specific logger for events
                "handlers": ["console", "api_file"], # Use same handlers as 'app'
                "level": LOG_LEVEL, # Use environment-based level
                "propagate": False,
            },
            "compliance": { # Specific logger for compliance
                "handlers": ["compliance_file"],
                "level": "INFO", # Always keep compliance logging at INFO
                "propagate": False,
            },
            # Configure noisy loggers
            "uvicorn": {
                "handlers": ["console", "api_file"], # Route uvicorn logs through our handlers
                "level": "WARNING" if IS_PRODUCTION else "INFO", # Restrict in production
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO", # Restrict in production
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "api_file"], # Route access logs too
                "level": "WARNING", # Keep access logs at WARNING
                "propagate": False,
            },
            "httpx": {
                "handlers": ["console", "api_file"],
                "level": "WARNING",
                "propagate": False,
            },
            "app.middleware.logging_middleware": { # Keep this specific setting
                "handlers": ["console", "api_file"],
                "level": "WARNING",
                "propagate": False,
            },
            
            # Loggers that contain sensitive information - restrict in production
            "backend.core.api.app.routes.auth_ws": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.routes.connection_manager": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.routes.websockets": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.services.cache_chat_mixin": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.utils.encryption": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.routes.handlers.websocket_handlers": {
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            
            # Other service loggers
            "app.routes.auth": { # Assuming this was intended for all auth routes
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "app.services.s3": { # Example: Ensure S3 logs are captured
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "app.services.cache": { # Example: Ensure Cache logs are captured
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "app.services.metrics": { # Example: Ensure Metrics logs are captured
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "app.services.directus": { # Example: Ensure Directus logs are captured
                "handlers": ["console", "api_file"],
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            # Add other specific 'app.*' loggers here if they need levels other than the base 'app' logger
        },
    "root": {
        # Remove handlers from the root logger.
        # If specific loggers are configured correctly with propagate=False,
        # the root logger shouldn't need to handle their messages directly.
        # It will still act as a fallback for unconfigured loggers if needed,
        # but won't output anything itself unless handlers are added elsewhere.
        "handlers": [],
        "level": LOG_LEVEL,
    },
}

def setup_logging():
    """Configures logging using dictConfig."""
    logging.config.dictConfig(LOGGING_CONFIG)
    # Filters are applied via the dictConfig structure ('filters' key in handlers)
    # No need to add them manually here unless for very specific cases.

    # The filter on 'app.middleware.logging_middleware' needs separate handling
    # as dictConfig doesn't directly support adding filters this way easily.
    # Re-apply the WARNING level filter after dictConfig.
    log_filter = logging.Filter()
    log_filter.filter = lambda record: record.levelno >= logging.WARNING
    logging.getLogger("app.middleware.logging_middleware").addFilter(log_filter)

    logger = logging.getLogger(__name__)
    if IS_PRODUCTION:
        logger.warning("Logging configured for PRODUCTION environment - sensitive INFO logs are disabled")
    else:
        logger.info("Logging configured for DEVELOPMENT environment - all log levels enabled")

# Example of how to use the compliance logger
# compliance_logger = logging.getLogger("compliance")
# compliance_logger.info({"event": "user_login", "user_id": "123", "status": "success"})

# Example of how to use the event logger
# event_logger = logging.getLogger("app.events")
# event_logger.info("User registration process started.")
