import logging
import logging.config
import os
import sys
from pythonjsonlogger import jsonlogger
from app.utils.log_filters import SensitiveDataFilter

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs") # Adjust path relative to this file
API_LOG_PATH = os.path.join(LOGS_DIR, "api.log")
COMPLIANCE_LOG_PATH = os.path.join(LOGS_DIR, "compliance.log")

# Create logs directory if it doesn't exist
os.makedirs(LOGS_DIR, exist_ok=True)

# Create sensitive data filter instance
sensitive_filter = SensitiveDataFilter() # Keep the filter instance

# We don't need a custom formatter class anymore if we apply filters to handlers
# class JsonFormatterWithFilter(jsonlogger.JsonFormatter):
#     def __init__(self, *args, **kwargs):
#         # Pass format string correctly if needed, or rely on default
#         fmt = kwargs.pop('format', None)
#         super().__init__(fmt=fmt, *args, **kwargs)
#         # Filters are added to handlers, not formatters
#         # self.addFilter(sensitive_filter)

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
                "level": "INFO", # Allow INFO for events
                "propagate": False,
            },
            "compliance": { # Specific logger for compliance
                "handlers": ["compliance_file"],
                "level": "INFO",
                "propagate": False,
            },
            # Configure noisy loggers
            "uvicorn": {
                "handlers": ["console", "api_file"], # Route uvicorn logs through our handlers
                "level": "INFO", # Let uvicorn log info by default, adjust if needed
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "api_file"],
                "level": "INFO",
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
            # Allow specific modules to be INFO even if root is WARNING
            "app.utils.encryption": {
                "handlers": ["console", "api_file"],
                "level": "INFO",
                "propagate": False,
            },
            "app.routes.auth": { # Assuming this was intended for all auth routes
                "handlers": ["console", "api_file"],
                "level": "INFO",
                "propagate": False,
            },
            "app.services.s3": { # Example: Ensure S3 logs are captured
                "handlers": ["console", "api_file"],
                "level": "INFO",
                "propagate": False,
            },
            "app.services.cache": { # Example: Ensure Cache logs are captured
                "handlers": ["console", "api_file"],
                "level": "INFO",
                "propagate": False,
            },
            "app.services.metrics": { # Example: Ensure Metrics logs are captured
                "handlers": ["console", "api_file"],
                "level": "INFO",
                "propagate": False,
            },
            "app.services.directus": { # Example: Ensure Directus logs are captured
                "handlers": ["console", "api_file"],
                "level": "INFO",
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

    logging.getLogger(__name__).info("Logging configured using dictConfig.")

# Example of how to use the compliance logger
# compliance_logger = logging.getLogger("compliance")
# compliance_logger.info({"event": "user_login", "user_id": "123", "status": "success"})

# Example of how to use the event logger
# event_logger = logging.getLogger("app.events")
# event_logger.info("User registration process started.")
